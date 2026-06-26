function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('Index').setTitle('紀念品倉存').setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// ── Public: 物品目錄（只出名稱+圖片） ──
function getCatalog() {
  var sheet = SpreadsheetApp.getActive().getSheetByName('庫存總表');
  var data = sheet.getDataRange().getValues();
  var items = [];
  for (var i = 1; i < data.length; i++) {
    if (data[i][0]) items.push({ name: data[i][0], image: data[i][5] || '' });
  }
  return items;
}

// ── Public: 提交申請 ──
function submitApplication(form) {
  var sheet = SpreadsheetApp.getActive().getSheetByName('一般宣傳品');
  var lastId = sheet.getRange(sheet.getLastRow(), 1).getValue();
  var m = String(lastId).match(/(\d+)\/2026/), num = m ? parseInt(m[1]) + 1 : 1;
  var newId = ('000' + num).slice(-3) + '/2026';
  var d = new Date();
  var ds = d.getFullYear() + '-' + ('0'+(d.getMonth()+1)).slice(-2) + '-' + ('0'+d.getDate()).slice(-2);
  
  var itemsText = form.items.map(function(it){ return it.name + '×' + it.qty; }).join(', ');
  
  // Write to main sheet with status column
  sheet.appendRow([newId, ds, form.category, form.reason + ' | ' + itemsText]);
  
  // Write to 審批表
  var apSheet = SpreadsheetApp.getActive().getSheetByName('審批表');
  if (!apSheet) {
    apSheet = SpreadsheetApp.getActive().insertSheet('審批表');
    apSheet.appendRow(['申請編號','日期','申請人','部門','分類','事由','物品','狀態','審批人','審批日期']);
  }
  apSheet.appendRow([newId, ds, form.applicant, form.department, form.category, form.reason, itemsText, '待審批', '', '']);
  
  return { status: 'submitted', id: newId, message: '申請 ' + newId + ' 已提交，等待主管審批' };
}

// ── Supervisor: 登入驗證 ──
function supervisorLogin(password) {
  var sheet = SpreadsheetApp.getActive().getSheetByName('系統設定');
  if (!sheet) return false;
  var data = sheet.getDataRange().getValues();
  for (var i = 0; i < data.length; i++) {
    if (data[i][0] === '主管密碼' && data[i][1] === password) return true;
  }
  return false;
}

// ── Supervisor: 庫存總覽 ──
function getStock() {
  var sheet = SpreadsheetApp.getActive().getSheetByName('庫存總表');
  var data = sheet.getDataRange().getValues();
  var items = [];
  for (var i = 1; i < data.length; i++) {
    if (data[i][0]) items.push({
      name: data[i][0], category: data[i][1] || '', initial: data[i][2] || 0,
      stock: data[i][3] || 0, safe: data[i][4] || 10, image: data[i][5] || ''
    });
  }
  return items;
}

// ── Supervisor: 審批列表 ──
function getApprovals() {
  var sheet = SpreadsheetApp.getActive().getSheetByName('審批表');
  if (!sheet) return [];
  var data = sheet.getDataRange().getValues();
  var apps = [];
  for (var i = 1; i < data.length; i++) {
    if (data[i][0]) apps.push({
      id: String(data[i][0]), date: String(data[i][1] || ''),
      applicant: data[i][2] || '', department: data[i][3] || '',
      category: data[i][4] || '', reason: data[i][5] || '',
      items: data[i][6] || '', status: data[i][7] || '待審批',
      approver: data[i][8] || '', approveDate: data[i][9] || ''
    });
  }
  return apps.reverse();
}

// ── Supervisor: 審批動作 ──
function approveApp(appId, action, approver) {
  var sheet = SpreadsheetApp.getActive().getSheetByName('審批表');
  if (!sheet) return { error: '審批表不存在' };
  var data = sheet.getDataRange().getValues();
  var d = new Date();
  var ds = d.getFullYear() + '-' + ('0'+(d.getMonth()+1)).slice(-2) + '-' + ('0'+d.getDate()).slice(-2);
  
  for (var i = 1; i < data.length; i++) {
    if (String(data[i][0]) === appId) {
      if (action === 'approve') {
        sheet.getRange(i+1, 8).setValue('已通過');
        sheet.getRange(i+1, 9).setValue(approver);
        sheet.getRange(i+1, 10).setValue(ds);
        
        // Deduct stock
        var itemsStr = data[i][6] || '';
        var itemList = itemsStr.split(', ');
        var stockSheet = SpreadsheetApp.getActive().getSheetByName('庫存總表');
        var sd = stockSheet.getDataRange().getValues();
        
        for (var j = 0; j < itemList.length; j++) {
          var parts = itemList[j].split('×');
          if (parts.length === 2) {
            var iname = parts[0].trim();
            var iqty = parseInt(parts[1]) || 0;
            for (var k = 1; k < sd.length; k++) {
              if (sd[k][0] === iname) {
                var current = parseInt(sd[k][3]) || 0;
                stockSheet.getRange(k+1, 4).setValue(current - iqty);
                break;
              }
            }
          }
        }
        return { status: 'approved', message: '申請 ' + appId + ' 已通過，庫存已扣減' };
      } else {
        sheet.getRange(i+1, 8).setValue('已拒絕');
        sheet.getRange(i+1, 9).setValue(approver);
        sheet.getRange(i+1, 10).setValue(ds);
        return { status: 'rejected', message: '申請 ' + appId + ' 已拒絕' };
      }
    }
  }
  return { error: '找不到申請' };
}

// ── Supervisor: 更新庫存 ──
function updateStock(name, newStock) {
  var sheet = SpreadsheetApp.getActive().getSheetByName('庫存總表');
  var data = sheet.getDataRange().getValues();
  for (var i = 1; i < data.length; i++) {
    if (data[i][0] === name) {
      sheet.getRange(i+1, 4).setValue(parseInt(newStock) || 0);
      return { status: 'ok', message: name + ' 庫存已更新為 ' + newStock };
    }
  }
  return { error: '找不到物品' };
}
