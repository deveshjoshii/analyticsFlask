from flask import Flask, request, jsonify
import os
import csv
import json
import urllib.parse
import time
from selenium import webdriver
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'

# Create upload folder if it doesn't exist
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

# Set up Chrome options for capturing performance logs
options = Options()
options.add_argument("--ignore-certificate-errors")
options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

# Initialize the WebDriver outside any route so it persists
driver = Chrome(options=options)


def read_urls_from_csv(file_path):
    """Read URLs from a CSV file and return a list of rows."""
    rows = []
    with open(file_path, mode='r') as file:
        csv_reader = csv.DictReader(file)
        for row in csv_reader:
            rows.append(row)
    return rows


def urlDecode(string):
    """URL decode the query string and return the parameters as a dictionary."""
    decoded_query_string = urllib.parse.unquote(string)
    params = dict(urllib.parse.parse_qsl(decoded_query_string))
    return params


def visitBrowser(row):
    """Visit the URL and capture network logs."""
    url = row['Url']
    driver.get(url)
    driver.implicitly_wait(10)

    requests_dict = {}
    timeout = 10
    end_time = time.time() + timeout

    while time.time() < end_time:
        logs = driver.get_log('performance')
        for log in logs:
            log_json = json.loads(log['message'])['message']
            if log_json['method'] == 'Network.responseReceived':
                response_url = log_json['params']['response']['url']
                if 'amexpressprod' in response_url or '/b/ss' in response_url:
                    request_data = {
                        'url': response_url,
                        'status': log_json['params']['response']['status'],
                        'headers': log_json['params']['response']['headers'],
                        'request_id': log_json['params']['requestId'],
                        'params': urlDecode(response_url.split('?')[-1]) if '?' in response_url else {}
                    }
                    requests_dict[request_data['request_id']] = request_data

        time.sleep(1)

    return requests_dict


def perform_action(action):
    """Perform the specified action on the page."""
    if action:
        action_parts = action.split('|')
        if len(action_parts) == 2:
            action_type, locator = action_parts
            element = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, locator.strip()))
            )
            if action_type.strip().lower() == 'click':
                element.click()


@app.route('/upload', methods=['GET', 'POST'])
def upload_file():
    """Handle file upload and processing."""
    if request.method == 'POST':
        if 'file' not in request.files:
            return jsonify({'error': 'No file part'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No selected file'}), 400

        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(file_path)

        rows = read_urls_from_csv(file_path)
        requests_dict = {}

        for row in rows:
            requests_dict.update(visitBrowser(row))
            if 'Action' in row and row['Action']:
                perform_action(row['Action'])

        for row in rows:
            fieldname = row['Fieldname'].strip()
            expected_value = row['Value'].strip()

            found = any(
                fieldname in req['params'] and req['params'][fieldname] == expected_value
                for req in requests_dict.values()
            )
            row['Status'] = 'Pass' if found else 'Fail'

        return jsonify({'message': 'File processed successfully!', 'rows': rows}), 200
    else:
        return '''
            <html>
                <body>
                    <h1>Upload a CSV file</h1>
                    <form action="/upload" method="post" enctype="multipart/form-data">
                        <input type="file" name="file" accept=".csv">
                        <input type="submit" value="Upload">
                    </form>
                </body>
            </html>
        '''


if __name__ == '__main__':
    try:
        app.run(debug=True)
    finally:
        driver.quit()  # Ensure the driver quits when the application ends
