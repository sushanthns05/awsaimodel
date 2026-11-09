/**
 * AWS Student Builder Group — Google Forms → AWS intake bridge
 * SJB Institute of Technology | Recruitment Cycle 2026-27
 *
 * Responsibilities
 *  - Runs on the form's installable submit trigger.
 *  - Preserves every form answer exactly as submitted.
 *  - Downloads uploaded resumes and sends them as base64 to the intake API.
 *  - Signs each request with HMAC-SHA256 and a shared intake key.
 *  - Queues failed submissions in a Drive folder and retries them later.
 *  - Never blocks the student's form submission.
 *
 * Setup: run setup() once from the Apps Script editor after setting
 * API_URL and INTAKE_KEY below (or store them in Script Properties).
 */

var CONFIG = {
  // Set these two values (or create Script Properties with the same names).
  API_URL: 'https://YOUR-API-ID.execute-api.ap-south-1.amazonaws.com/prod/intake',
  INTAKE_KEY: '',

  FORM_ID: '',                 // Optional. Defaults to the form bound to this script.
  SHEET_NAME: 'Form Responses 1',

  MAX_DOCUMENT_BYTES: 6 * 1024 * 1024,
  MAX_DOCUMENTS: 6,
  REQUEST_TIMEOUT_SECONDS: 60,
  RETRY_FOLDER_NAME: 'SBG Recruitment Pending Submissions',
  SENT_CACHE_PREFIX: 'sbg_sent_',
  SENT_CACHE_SECONDS: 60 * 60 * 24 * 30,

  // Question titles that may contain uploaded file links. Adjust if needed.
  FILE_QUESTION_HINTS: ['resume', 'cv', 'portfolio', 'upload', 'document'],

  // Optional canonical aliases used only for local logging/metadata.
  // The authoritative field mapping lives in the AWS dashboard Settings page.
  ANSWER_ALIASES: {
    full_name: ['Full Name', 'Name', 'Student Name'],
    email: ['Email Address', 'Email', 'College Email'],
    usn: ['University Seat Number (USN)', 'USN', 'Seat Number'],
    phone: ['Phone Number', 'Mobile Number', 'Contact Number'],
    department: ['Department', 'Branch'],
    year_of_study: ['Year of Study', 'Year'],
    roles: ['Which team(s) are you applying for?', 'Preferred Team', 'Roles']
  }
};

/** Creates triggers and ensures the retry folder exists. Run once. */
function setup() {
  var props = PropertiesService.getScriptProperties();
  if (CONFIG.API_URL && CONFIG.API_URL.indexOf('YOUR-API-ID') === -1) {
    props.setProperty('API_URL', CONFIG.API_URL);
  }
  if (CONFIG.INTAKE_KEY) {
    props.setProperty('INTAKE_KEY', CONFIG.INTAKE_KEY);
  }
  if (!props.getProperty('API_URL') || !props.getProperty('INTAKE_KEY')) {
    throw new Error('Set API_URL and INTAKE_KEY in CONFIG or Script Properties before running setup().');
  }

  var existing = ScriptApp.getProjectTriggers();
  for (var i = 0; i < existing.length; i++) {
    var fn = existing[i].getHandlerFunction();
    if (fn === 'onFormSubmit' || fn === 'retryPending' || fn === 'reconcileResponses') {
      ScriptApp.deleteTrigger(existing[i]);
    }
  }

  ScriptApp.newTrigger('onFormSubmit').forSpreadsheet(SpreadsheetApp.getActive()).onFormSubmit().create();
  ScriptApp.newTrigger('retryPending').timeBased().everyMinutes(15).create();
  ScriptApp.newTrigger('reconcileResponses').timeBased().everyHours(6).create();

  getRetryFolder_();
  Logger.log('Setup complete: submit trigger, retry trigger and reconciliation trigger installed.');
}

/**
 * Installable form submit handler. The sheet-bound trigger provides
 * e.namedValues and e.values (file uploads appear as Drive links).
 */
function onFormSubmit(e) {
  if (!e || !e.namedValues) {
    Logger.log('No event payload. Run setup() and submit the form, or call backfillAllResponses().');
    return;
  }
  var responseId = '';
  try {
    responseId = e.response ? e.response.getId() : '';
  } catch (err) {
    responseId = '';
  }
  if (!responseId) {
    responseId = fingerprint_(JSON.stringify(e.namedValues));
  }
  var timestamp = firstValue_(e.namedValues['Timestamp']) || new Date().toISOString();
  submitNamedValues_(e.namedValues, responseId, timestamp);
}

/**
 * Builds and submits a payload. Never throws to the student; failures are
 * persisted to Drive for the retry trigger.
 */
function submitNamedValues_(namedValues, responseId, timestamp) {
  var props = PropertiesService.getScriptProperties();
  var cache = CacheService.getScriptCache();
  if (cache.get(CONFIG.SENT_CACHE_PREFIX + responseId)) {
    Logger.log('Response %s already submitted; skipping duplicate.', responseId);
    return;
  }

  var payload = {
    schema_version: 1,
    source: 'google_form',
    form_id: props.getProperty('FORM_ID') || CONFIG.FORM_ID || '',
    form_title: getFormTitle_(),
    source_response_id: responseId,
    submitted_at: new Date(timestamp).toISOString(),
    answers: {},
    documents: [],
    document_errors: []
  };

  Object.keys(namedValues).forEach(function (question) {
    payload.answers[question] = firstValue_(namedValues[question]);
  });

  payload.documents = collectDocuments_(namedValues, payload.document_errors);

  try {
    var result = postToAws_(payload);
    cache.put(CONFIG.SENT_CACHE_PREFIX + responseId, '1', CONFIG.SENT_CACHE_SECONDS);
    Logger.log('Submitted %s → HTTP %s %s', responseId, result.code, result.body);
  } catch (err) {
    Logger.log('Submission failed for %s: %s. Queued for retry.', responseId, err);
    queueForRetry_(payload);
  }
}

/** Retries every queued payload. Installed as a 15-minute trigger. */
function retryPending() {
  var folder = getRetryFolder_();
  var files = folder.getFiles();
  var processed = 0;
  while (files.hasNext() && processed < 20) {
    var file = files.next();
    processed++;
    try {
      var payload = JSON.parse(file.getBlob().getDataAsString());
      var result = postToAws_(payload);
      CacheService.getScriptCache().put(CONFIG.SENT_CACHE_PREFIX + payload.source_response_id, '1', CONFIG.SENT_CACHE_SECONDS);
      file.setTrashed(true);
      Logger.log('Retried %s → HTTP %s %s', payload.source_response_id, result.code, result.body);
    } catch (err) {
      Logger.log('Retry failed for %s: %s', file.getName(), err);
    }
  }
}

/**
 * Reconciliation: resubmits rows that were never acknowledged by AWS.
 * Uses a Drive marker per response ID; safe to run repeatedly.
 */
function reconcileResponses() {
  var sheet = getResponseSheet_();
  if (!sheet) {
    Logger.log('Response sheet not found.');
    return;
  }
  var lastRow = sheet.getLastRow();
  if (lastRow < 2) return;
  var values = sheet.getDataRange().getValues();
  var headers = values[0];
  var responseIdIndex = headers.indexOf('Response ID');
  var timestampIndex = headers.indexOf('Timestamp');
  var limit = Math.min(values.length, 500);

  for (var row = 1; row < limit; row++) {
    var rowValues = values[row];
    var responseId = responseIdIndex >= 0 ? String(rowValues[responseIdIndex]) : fingerprint_(rowValues.join('|'));
    if (!responseId) continue;
    var marker = DriveApp.getFilesByName('sbg-ack-' + responseId);
    if (marker.hasNext()) continue;
    if (DriveApp.getFilesByName(responseId + '.json').hasNext()) continue; // queued already

    var namedValues = {};
    for (var col = 0; col < headers.length; col++) {
      namedValues[headers[col]] = [rowValues[col]];
    }
    submitNamedValues_(namedValues, responseId, rowValues[timestampIndex] || new Date().toISOString());
  }
}

/** Manual backfill from the editor. */
function backfillAllResponses() {
  reconcileResponses();
}

/**
 * Extracts Drive file links from upload questions, downloads them, converts
 * Google-native files to PDF and base64-encodes the bytes.
 */
function collectDocuments_(namedValues, errors) {
  var documents = [];
  Object.keys(namedValues).forEach(function (question) {
    var text = String(firstValue_(namedValues[question]) || '');
    var lower = question.toLowerCase();
    var looksLikeFile = CONFIG.FILE_QUESTION_HINTS.some(function (hint) {
      return lower.indexOf(hint) !== -1;
    });
    if (!text || (!looksLikeFile && text.indexOf('drive.google.com') === -1)) return;

    var ids = extractDriveIds_(text);
    if (!ids.length) return;
    ids.slice(0, CONFIG.MAX_DOCUMENTS).forEach(function (fileId) {
      try {
        var file = DriveApp.getFileById(fileId);
        var blob = file.getBlob();
        var name = file.getName();
        if (file.getMimeType().indexOf('google-apps') !== -1) {
          blob = file.getAs(MimeType.PDF);
          name = name + '.pdf';
        }
        var bytes = blob.getBytes();
        if (bytes.length > CONFIG.MAX_DOCUMENT_BYTES) {
          errors.push(name + ': file exceeds ' + (CONFIG.MAX_DOCUMENT_BYTES / (1024 * 1024)) + ' MB limit');
          return;
        }
        documents.push({
          name: name,
          mime_type: blob.getContentType(),
          source_url: 'https://drive.google.com/file/d/' + fileId + '/view',
          base64: Utilities.base64Encode(bytes)
        });
      } catch (err) {
        errors.push('Could not read uploaded file ' + fileId + ': ' + err);
      }
    });
  });
  return documents.slice(0, CONFIG.MAX_DOCUMENTS);
}

function postToAws_(payload) {
  var props = PropertiesService.getScriptProperties();
  var url = props.getProperty('API_URL');
  var key = props.getProperty('INTAKE_KEY');
  if (!url || !key) throw new Error('API_URL or INTAKE_KEY is not configured');

  var body = JSON.stringify(payload);
  var timestamp = String(Math.floor(Date.now() / 1000));
  var signature = hmacHex_(timestamp + '.' + body, key);

  var response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    payload: body,
    headers: {
      'X-Intake-Key': key,
      'X-Timestamp': timestamp,
      'X-Signature': signature
    },
    muteHttpExceptions: true,
    followRedirects: false,
    timeout: CONFIG.REQUEST_TIMEOUT_SECONDS
  });

  var code = response.getResponseCode();
  var text = response.getContentText();
  if (code < 200 || code >= 300) {
    throw new Error('HTTP ' + code + ': ' + text.substring(0, 500));
  }
  if (text.indexOf('"status":"DUPLICATE"') !== -1 || text.indexOf('"status": "DUPLICATE"') !== -1) {
    Logger.log('Server reports duplicate for %s', payload.source_response_id);
  }
  // Write an acknowledgement marker for reconciliation.
  try {
    getRetryFolder_().createFile('sbg-ack-' + payload.source_response_id, 'ok');
  } catch (err) {
    Logger.log('Unable to write ack marker: %s', err);
  }
  return { code: code, body: text.substring(0, 500) };
}

function queueForRetry_(payload) {
  var folder = getRetryFolder_();
  var name = payload.source_response_id + '.json';
  var existing = folder.getFilesByName(name);
  if (existing.hasNext()) return;
  folder.createFile(name, JSON.stringify(payload), MimeType.PLAIN_TEXT);
}

function getRetryFolder_() {
  var it = DriveApp.getFoldersByName(CONFIG.RETRY_FOLDER_NAME);
  return it.hasNext() ? it.next() : DriveApp.createFolder(CONFIG.RETRY_FOLDER_NAME);
}

function getFormTitle_() {
  try {
    var id = PropertiesService.getScriptProperties().getProperty('FORM_ID') || CONFIG.FORM_ID;
    if (id) return FormApp.openById(id).getTitle();
    var form = FormApp.getActiveForm();
    return form ? form.getTitle() : 'AWS Student Builder Group Recruitment';
  } catch (err) {
    return 'AWS Student Builder Group Recruitment';
  }
}

function getResponseSheet_() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  if (!ss) return null;
  return ss.getSheetByName(CONFIG.SHEET_NAME) || ss.getSheets()[0];
}

function extractDriveIds_(text) {
  var ids = [];
  var patterns = [
    /\/file\/d\/([a-zA-Z0-9_-]{20,})/g,
    /[?&]id=([a-zA-Z0-9_-]{20,})/g,
    /\/d\/([a-zA-Z0-9_-]{20,})/g
  ];
  patterns.forEach(function (re) {
    var match;
    while ((match = re.exec(text)) !== null) {
      if (ids.indexOf(match[1]) === -1) ids.push(match[1]);
    }
  });
  return ids;
}

function hmacHex_(message, secret) {
  var bytes = Utilities.computeHmacSha256Signature(message, secret);
  var hex = '';
  for (var i = 0; i < bytes.length; i++) {
    var v = (bytes[i] < 0 ? bytes[i] + 256 : bytes[i]).toString(16);
    hex += v.length === 1 ? '0' + v : v;
  }
  return hex;
}

function fingerprint_(value) {
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, String(value));
  return digest.map(function (b) {
    var v = (b < 0 ? b + 256 : b).toString(16);
    return v.length === 1 ? '0' + v : v;
  }).join('').substring(0, 32);
}

function firstValue_(value) {
  if (value === null || value === undefined) return '';
  if (Object.prototype.toString.call(value) === '[object Array]') {
    return value.length ? String(value[0]) : '';
  }
  return String(value);
}
