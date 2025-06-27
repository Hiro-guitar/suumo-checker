from googleapiclient.discovery import build
from google.oauth2 import service_account
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json

# === 定数 ===
SPREADSHEET_ID_SOURCE = '1oZKxfoZbFWzTfZvSU_ZVHtnWLDmJDYNd6MSfNqlB074'
SOURCE_RANGE = 'シート1!A:J'
SPREADSHEET_ID_LOG = '195OS2gb97TUJS8srYlqLT5QXuXU0zUZxmbeuWtsGQRY'
LOG_SHEET_NAME = 'Sheet1'
SHEET_ID_LOG = 0  # 通常Sheet1は0（違う場合は変更）
KEYWORD = 'えほうまき'
BASE_URL = 'https://suumo.jp'
now_label = datetime.now(ZoneInfo("Asia/Tokyo")).strftime('%Y/%m/%d %H:%M')

# === 認証 ===
def get_service():
    with open('service_account.json', 'r') as f:
        service_account_info = json.load(f)
    creds = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)

# === 元シートのデータ取得 ===
def get_source_data(service):
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID_SOURCE, range=SOURCE_RANGE).execute()
    values = result.get('values', [])
    return [(row[0], row[9]) for row in values if len(row) >= 10 and row[0] and row[9].startswith('http')]

# === 代表URL抽出 ===
def extract_detail_links(start_url):
    try:
        res = requests.get(start_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        return [BASE_URL + a['href'] for a in soup.find_all('a', href=True) if '/chintai/' in a['href'] and 'jnc_' in a['href']]
    except Exception as e:
        print(f"[ERROR] {start_url} のリンク取得失敗: {e}")
        return []

# === キーワードチェック ===
def check_keyword_in_page(detail_url):
    try:
        res = requests.get(detail_url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        target = soup.select_one('.viewform_advance_shop-name')
        text = target.get_text() if target else soup.get_text()
        return KEYWORD in text, None
    except Exception as e:
        return False, str(e)

# === ログの読み込み（行番号付き）===
def load_existing_log(service):
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID_LOG, range=LOG_SHEET_NAME).execute()
    rows = result.get('values', [])
    headers = rows[0] if rows else ['物件名', '元ページURL', '代表物件URL']
    existing_data = {}
    for i, row in enumerate(rows[1:], start=2):  # 行番号は2から（1はヘッダー）
        key = tuple(row[:3])
        existing_data[key] = (i, row)
    return headers, existing_data

# === 保存 ===
def save_log_to_sheet(service, headers, data_rows):
    values = [headers] + list(data_rows.values())
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID_LOG,
        range=LOG_SHEET_NAME,
        valueInputOption='RAW',
        body={'values': values}
    ).execute()

# === メイン ===
def main():
    service = get_service()
    entries = get_source_data(service)
    headers, existing_data = load_existing_log(service)

    # ヘッダーに現在時刻の列を追加
    if now_label not in headers:
        headers.append(now_label)
    now_index = headers.index(now_label)

    # 削除対象（元データに存在しないもの）
    valid_entry_keys = {(name, url) for name, url in entries}
    rows_to_delete = [
        row_num for (name, url, _), (row_num, _) in existing_data.items()
        if (name, url) not in valid_entry_keys
    ]

    if rows_to_delete:
        rows_to_delete.sort(reverse=True)
        delete_requests = [{
            "deleteDimension": {
                "range": {
                    "sheetId": SHEET_ID_LOG,
                    "dimension": "ROWS",
                    "startIndex": row_num - 1,
                    "endIndex": row_num
                }
            }
        } for row_num in rows_to_delete]

        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID_LOG,
            body={"requests": delete_requests}
        ).execute()
        print(f"🗑️ {len(rows_to_delete)} 件の削除済み物件をログから削除しました")

    # 削除済み行を反映するため再読込
    headers, existing_data = load_existing_log(service)
    if now_label not in headers:
        headers.append(now_label)
    now_index = headers.index(now_label)

    for name, start_url in entries:
        detail_links = extract_detail_links(start_url)
        if not detail_links:
            key = (name, start_url, '')
            if key not in existing_data:
                existing_data[key] = (None, [name, start_url, ''] + [''] * (len(headers) - 3))
            row = existing_data[key][1]
            while len(row) < len(headers):
                row.append('')
            row[now_index] = 'NO DETAIL LINKS FOUND'
            continue

        for detail_url in detail_links:
            key = (name, start_url, detail_url)
            if key not in existing_data:
                existing_data[key] = (None, [name, start_url, detail_url] + [''] * (len(headers) - 3))
            row = existing_data[key][1]
            while len(row) < len(headers):
                row.append('')
            found, error = check_keyword_in_page(detail_url)
            result = '⭕️' if found else f'ERROR: {error}' if error else ''
            row[now_index] = result

    # 保存
    final_data = {k: v[1] for k, v in existing_data.items()}
    for row in final_data.values():
        while len(row) < len(headers):
            row.append('')
    save_log_to_sheet(service, headers, final_data)
    print("✅ ログを更新し、取得時間の記録も正常です")

if __name__ == '__main__':
    main()
