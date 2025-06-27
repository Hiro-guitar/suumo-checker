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
KEYWORD = 'えほうまき'
BASE_URL = 'https://suumo.jp'
now_label = datetime.now(ZoneInfo("Asia/Tokyo")).strftime('%Y/%m/%d %H:%M')

# === Google Sheets API 認証 ===
def get_service():
    with open('service_account.json', 'r') as f:
        service_account_info = json.load(f)
    creds = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)

# === 元データ取得 ===
def get_source_data(service):
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID_SOURCE, range=SOURCE_RANGE).execute()
    values = result.get('values', [])
    data = []
    for row in values:
        name = row[0] if len(row) >= 1 else ''
        url = row[9] if len(row) >= 10 and row[9].startswith('http') else ''
        if name and url:
            data.append((name, url))
    return data

# === 代表物件リンク抽出 ===
def extract_detail_links(start_url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        res = requests.get(start_url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        links = [BASE_URL + a['href'] for a in soup.find_all('a', href=True) if '/chintai/' in a['href'] and 'jnc_' in a['href']]
        return links
    except Exception as e:
        print(f"[ERROR] {start_url} のリンク取得失敗: {e}")
        return []

# === キーワードチェック ===
def check_keyword_in_page(detail_url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0'
        }
        res = requests.get(detail_url, headers=headers, timeout=15)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')

        # 該当要素がなければ全文検索
        target = soup.select_one('.viewform_advance_shop-name')
        text = target.get_text() if target else soup.get_text()

        return KEYWORD in text, None
    except Exception as e:
        return False, str(e)

# === ログの読み込み（代表URLは信用せず、ログの構造だけ使う） ===
def load_existing_log(service):
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID_LOG, range=LOG_SHEET_NAME).execute()
    rows = result.get('values', [])
    headers = rows[0] if rows else ['物件名', '元ページURL', '代表物件URL']
    existing_data = {tuple(row[:3]): row for row in rows[1:]} if len(rows) > 1 else {}
    return headers, existing_data

# === ログを保存 ===
def save_log_to_sheet(service, headers, data_rows):
    body = {
        'values': [headers] + list(data_rows.values())
    }
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID_LOG,
        range=LOG_SHEET_NAME,
        valueInputOption='RAW',
        body=body
    ).execute()

# === メイン処理 修正版 ===
def main():
    service = get_service()
    entries = get_source_data(service)
    headers, existing_data = load_existing_log(service)

    if now_label not in headers:
        headers.append(now_label)

    for name, start_url in entries:
        detail_links = extract_detail_links(start_url)

        if not detail_links:
            key = (name, start_url, '')
            if key not in existing_data:
                existing_data[key] = [name, start_url, ''] + [''] * (len(headers) - 4)
            while len(existing_data[key]) < len(headers) - 1:
                existing_data[key].append('')
            existing_data[key].append('NO DETAIL LINKS FOUND')
            continue

        for detail_url in detail_links:
            key = (name, start_url, detail_url)
            if key not in existing_data:
                existing_data[key] = [name, start_url, detail_url] + [''] * (len(headers) - 4)
            while len(existing_data[key]) < len(headers) - 1:
                existing_data[key].append('')
            found, error = check_keyword_in_page(detail_url)
            result = '⭕️' if found else f'ERROR: {error}' if error else ''
            existing_data[key].append(result)

    # 行の長さを統一
    for row in existing_data.values():
        while len(row) < len(headers):
            row.append('')

    save_log_to_sheet(service, headers, existing_data)
    print("✅ 過去のログを保持したまま、最新の結果を追記しました")

if __name__ == '__main__':
    main()
