/**
 * SMG 紀念品倉存管理系統 — Google Apps Script 後端
 * 部署方式：Publish → Deploy as web app → Execute as "Me" → Access: "Anyone"
 * 將 deployment URL 貼到前端的 API_BASE
 */

// === CONFIG ===
var SPREADSHEET_ID = 'YOUR_SPREADSHEET_ID'; // 替換為你的 Google Sheet ID
var SHEET_INVENTORY = '一般宣傳品';           // 庫存主表
var SHEET_APPLICATIONS = '申請記錄';           // 申請記錄表（自動建立）
var APPROVER_EMAIL = 'jeffreykan97@gmail.com'; // 審批人 email

// === ITEM DEFINITION — 從庫存表 row 3 解析 ===
function getItemList() {
  var sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEET_INVENTORY);
  var headerRow = sheet.getRange(3, 1, 1, sheet.getLastColumn()).getValues()[0];
  
  var items = [];
  var currentItem = '';
  for (var i = 4; i < headerRow.length; i++) { // col 5 onwards are items
    var val = headerRow[i];
    if (val && val.toString().trim()) {
      currentItem = val.toString().trim();
      items.push({ 
        id: i + 1, // 1-based column
        col: i + 1,
        name: currentItem,
        stock: getStock(i + 1)
      });
    }
  }
  return items;
}

// === 讀取庫存（指定 column 的餘額） ===
function getStock(col) {
  var sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEET_INVENTORY);
  var inventoryRow = sheet.getRange(348, 1, 2, sheet.getLastColumn()).getValues(); // row 348-349 餘額
  for (var r = 0; r < inventoryRow.length; r++) {
    if (inventoryRow[r][col - 1] && !isNaN(inventoryRow[r][col - 1])) {
      return Number(inventoryRow[r][col - 1]);
    }
  }
  return 0;
}

// === 庫存扣減 ===
function deductStock(col, qty) {
  var sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEET_INVENTORY);
  // 在 row 348 (餘額行) 扣減
  var balanceRow = 348;
  var current = sheet.getRange(balanceRow, col).getValue();
  sheet.getRange(balanceRow, col).setValue(Number(current) - Number(qty));
  return Number(current) - Number(qty);
}

// === 庫存增加（存入） ===
function addStock(col, qty) {
  var sheet = SpreadsheetApp.openById(SPREADSHEET_ID).getSheetByName(SHEET_INVENTORY);
  var balanceRow = 348;
  var current = sheet.getRange(balanceRow, col).getValue();
  sheet.getRange(balanceRow, col).setValue(Number(current) + Number(qty));
  return Number(current) + Number(qty);
}

// === 記錄申請 ===
function logApplication(data) {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(SHEET_APPLICATIONS);
  
  // 自動建立申請記錄表
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_APPLICATIONS);
    sheet.appendRow(['申請編號', '日期', '申請人', '部門', '事由', '分類', 
                     '物品', '數量', '狀態', '審批人', '審批日期', '備註']);
  }
  
  var appId = 'APP' + Utilities.formatDate(new Date(), 'GMT+8', 'yyyyMMdd') + '-' + 
              (sheet.getLastRow()).toString().padStart(3, '0');
  
  sheet.appendRow([
    appId,
    new Date(),
    data.applicant,
    data.department,
    data.reason,
    data.category,
    data.items.map(function(i) { return i.name + ' x' + i.qty; }).join(', '),
    data.items.reduce(function(s, i) { return s + i.qty; }, 0),
    '待審批',
    APPROVER_EMAIL,
    '',
    data.notes || ''
  ]);
  
  return appId;
}

// === API 入口 ===
function doGet(e) {
  var action = e.parameter.action;
  
  if (action === 'items') {
    return ContentService.createTextOutput(JSON.stringify({
      status: 'ok',
      items: getItemList()
    })).setMimeType(ContentService.MimeType.JSON);
  }
  
  if (action === 'applications') {
    return ContentService.createTextOutput(JSON.stringify({
      status: 'ok',
      applications: getApplications()
    })).setMimeType(ContentService.MimeType.JSON);
  }
  
  return ContentService.createTextOutput(JSON.stringify({
    status: 'error',
    message: 'Unknown action'
  })).setMimeType(ContentService.MimeType.JSON);
}

function doPost(e) {
  var data = JSON.parse(e.postData.contents);
  var action = data.action;
  
  if (action === 'apply') {
    // 驗證庫存
    var items = data.items;
    for (var i = 0; i < items.length; i++) {
      var stock = getStock(items[i].col);
      if (stock < items[i].qty) {
        return ContentService.createTextOutput(JSON.stringify({
          status: 'error',
          message: '物品「' + items[i].name + '」庫存不足（現有：' + stock + '，申請：' + items[i].qty + '）'
        })).setMimeType(ContentService.MimeType.JSON);
      }
    }
    
    // 記錄申請（狀態：待審批）
    var appId = logApplication(data);
    
    // 發送審批通知
    sendApprovalEmail(appId, data);
    
    return ContentService.createTextOutput(JSON.stringify({
      status: 'ok',
      message: '申請已提交，編號：' + appId + '，等待主管審批',
      appId: appId
    })).setMimeType(ContentService.MimeType.JSON);
  }
  
  if (action === 'approve') {
    approveApplication(data.appId);
    return ContentService.createTextOutput(JSON.stringify({
      status: 'ok',
      message: '已批准申請 ' + data.appId
    })).setMimeType(ContentService.MimeType.JSON);
  }
  
  if (action === 'reject') {
    rejectApplication(data.appId, data.reason);
    return ContentService.createTextOutput(JSON.stringify({
      status: 'ok',
      message: '已拒絕申請 ' + data.appId
    })).setMimeType(ContentService.MimeType.JSON);
  }
  
  return ContentService.createTextOutput(JSON.stringify({
    status: 'error',
    message: 'Unknown action'
  })).setMimeType(ContentService.MimeType.JSON);
}

// === 申請記錄 ===
function getApplications() {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(SHEET_APPLICATIONS);
  if (!sheet) return [];
  
  var data = sheet.getDataRange().getValues();
  var apps = [];
  for (var i = 1; i < data.length; i++) {
    apps.push({
      id: data[i][0],
      date: data[i][1],
      applicant: data[i][2],
      department: data[i][3],
      reason: data[i][4],
      items: data[i][6],
      status: data[i][8]
    });
  }
  return apps.reverse(); // 最新在前
}

// === 審批 ===
function approveApplication(appId) {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(SHEET_APPLICATIONS);
  var data = sheet.getDataRange().getValues();
  
  for (var i = 1; i < data.length; i++) {
    if (data[i][0] === appId) {
      // 扣庫存
      var itemsStr = data[i][6];
      // Parse items and deduct
      sheet.getRange(i + 1, 9).setValue('已批准'); // status
      sheet.getRange(i + 1, 11).setValue(new Date()); // approve date
      break;
    }
  }
}

function rejectApplication(appId, reason) {
  var ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  var sheet = ss.getSheetByName(SHEET_APPLICATIONS);
  var data = sheet.getDataRange().getValues();
  
  for (var i = 1; i < data.length; i++) {
    if (data[i][0] === appId) {
      sheet.getRange(i + 1, 9).setValue('已拒絕');
      sheet.getRange(i + 1, 12).setValue(reason || '');
      break;
    }
  }
}

// === Email 通知 ===
function sendApprovalEmail(appId, data) {
  var itemsList = data.items.map(function(i) { 
    return '  • ' + i.name + ' × ' + i.qty; 
  }).join('\n');
  
  var body = '有新的紀念品申請需要審批：\n\n' +
    '申請編號：' + appId + '\n' +
    '申請人：' + data.applicant + '\n' +
    '部門：' + data.department + '\n' +
    '事由：' + data.reason + '\n' +
    '物品：\n' + itemsList + '\n\n' +
    '批准：' + ScriptApp.getService().getUrl() + '?action=approve&id=' + appId + '\n' +
    '拒絕：回覆此郵件並說明原因';
  
  MailApp.sendEmail({
    to: APPROVER_EMAIL,
    subject: '【審批】紀念品申請 - ' + appId,
    body: body
  });
}
