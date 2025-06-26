from googleapiclient.discovery import build
from google.oauth2 import service_account
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from zoneinfo import ZoneInfo
import os
import json

# === 認証と設定 ===
SPREADSHEET_ID_SOURCE = '1oZKxfoZbFWzTfZvSU_ZVHtnWLDmJDYNd6MSfNqlB074'
SOURCE_RANGE = 'シート1!A:J'

SPREADSHEET_ID_LOG = '195OS2gb97TUJS8srYlqLT5QXuXU0zUZxmbeuWtsGQRY'
LOG_SHEET_NAME = 'Sheet1'

KEYWORD = 'えほうまき'
BASE_URL = 'https://suumo.jp'
now_label = datetime.now(ZoneInfo("Asia/Tokyo")).strftime('%m月%d日%H時%M分')

# === 認証取得 ===
def get_service():
    json_str = os.environ['GOOGLE_SERVICE_ACCOUNT_JSON']
    service_account_info = json.loads(json_str)

    creds = service_account.Credentials.from_service_account_info(
        service_account_info,
        scopes=['https://www.googleapis.com/auth/spreadsheets']
    )
    return build('sheets', 'v4', credentials=creds)

# === ソースシートから取得 ===
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

# === リンク取得 ===
def extract_detail_links(start_url):
    try:
        res = requests.get(start_url, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        links = [BASE_URL + a['href'] for a in soup.find_all('a', href=True) if a['href'].startswith('/chintai/jnc_')]
        return links
    except Exception as e:
        print(f"[ERROR] {start_url} のリンク取得に失敗: {e}")
        return []

# === キーワードチェック ===
def check_keyword_in_page(detail_url):
    try:
        res = requests.get(detail_url, timeout=10)
        res.encoding = res.apparent_encoding
        soup = BeautifulSoup(res.text, 'html.parser')
        target = soup.select_one('.viewform_advance_shop-name')
        return KEYWORD in target.get_text() if target else False, None
    except Exception as e:
        return False, str(e)

# === ログスプレッドシートの読み込み ===
def load_existing_log(service):
    sheet = service.spreadsheets()
    result = sheet.values().get(spreadsheetId=SPREADSHEET_ID_LOG, range=LOG_SHEET_NAME).execute()
    rows = result.get('values', [])
    headers = rows[0] if rows else ['物件名', '元ページURL', '代表物件URL']
    existing_data = {tuple(row[:3]): row for row in rows[1:]} if len(rows) > 1 else {}
    return headers, existing_data

# === ログをスプレッドシートに保存 ===
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

# === メイン ===
def main():
    service = get_service()
    entries = get_source_data(service)
    headers, existing_data = load_existing_log(service)

    if now_label not in headers:
        headers.append(now_label)

    new_keys = set()

    for name, start_url in entries:
        detail_links = extract_detail_links(start_url)
        if not detail_links:
            key = (name, start_url, '')
            new_keys.add(key)
            if key not in existing_data:
                existing_data[key] = [name, start_url, ''] + [''] * (len(headers) - 4)
            existing_data[key].append('NO DETAIL LINKS FOUND')
            continue

        for detail_url in detail_links:
            key = (name, start_url, detail_url)
            new_keys.add(key)
            if key not in existing_data:
                existing_data[key] = [name, start_url, detail_url] + [''] * (len(headers) - 4)
            found, error = check_keyword_in_page(detail_url)
            result = '⭕️' if found else f'ERROR: {error}' if error else ''
            existing_data[key].append(result)

    # 日付列が増えたことで不足している行を補完
    for row in existing_data.values():
        while len(row) < len(headers):
            row.append('')

    # 不要な行（削除済みの物件）を除外
    filtered_data = {k: v for k, v in existing_data.items() if k in new_keys}

    save_log_to_sheet(service, headers, filtered_data)
    print("✅ ログを書き込みました")

if __name__ == '__main__':
    main()
