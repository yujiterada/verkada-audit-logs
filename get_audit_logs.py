import argparse
from dotenv import load_dotenv
import json
import logging
import os
import requests
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Generator
from requests.exceptions import ConnectionError, Timeout, RequestException

VERKADA_ENVIRONMENT_VARIABLE_API_KEY = "VERKADA_API_KEY"
DEFAULT_BASE_URL = "https://api.au.verkada.com"
DEFAULT_SESSION_TIMEOUT = 30
DEFAULT_PAGE_SIZE = 100
DEFAULT_TOKEN_EXPIRATION_TIME = 25  # 25 minutes
RETRY_WAIT_TIME = 10
MAX_RETRIES = 3
INTERESTED_EVENTS = ['Archive Action Taken', 'Video History Streamed', 'Live Stream Started']
CRON_INTERVAL_MINUTES = 15  # Interval in minutes for cron job execution

load_dotenv()
# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def clean_params(params):
    """Remove keys with None values"""
    return {k: v for k, v in params.items() if v is not None}


class VerkadaAuthenticationError(Exception):
    """Exception for authentication errors"""
    pass


class VerkadaTokenExpiredError(Exception):
    """Exception for token expired errors"""
    pass


class VerkadaConnectionError(Exception):
    """Exception for connection errors"""
    pass

# Create a mock response object with the aggregated data
class MockResponse:
    def __init__(self, original_response, new_data):
        self._original = original_response
        self._data = new_data
        
    def json(self):
        return self._data
        
    # Delegate other attributes to original response
    def __getattr__(self, name):
        return getattr(self._original, name)

class VerkadaSession:
    """Session class for handling HTTP requests with retries and error handling"""

    def __init__(self, timeout=DEFAULT_SESSION_TIMEOUT):
        self.session = requests.Session()
        self.timeout = timeout
        self.max_retries = MAX_RETRIES

    def request(self, method, url, **kwargs):
        retries = self.max_retries
        last_exception = None

        while retries > 0:
            try:
                logger.info(
                    f"Making {method} request to {url} (retries left: {retries})")
                response = self.session.request(
                    method=method, url=url, timeout=self.timeout, **kwargs)
                status = response.status_code
                reason = response.reason if response.reason else ''

                # Handle response
                if 200 <= status < 300:
                    logger.info(f"Request successful: {status}")
                    return response
                if status == 401:
                    raise VerkadaTokenExpiredError(f"Token expired")
                elif status == 409:
                    raise VerkadaAuthenticationError(
                        f"Authentication error: Bad API key or token")
                elif status == 429:
                    logger.warning(
                        f"Rate limit hit, waiting {RETRY_WAIT_TIME} seconds...")
                    time.sleep(RETRY_WAIT_TIME)
                    retries -= 1
                    continue
                elif 500 <= status:
                    logger.warning(
                        f"Server error {status} {reason} for {method} {url}")
                    retries -= 1
                    if retries > 0:
                        wait_time = (self.max_retries - retries) * \
                            RETRY_WAIT_TIME  # Exponential backoff
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    continue
                elif 400 <= status < 500:
                    logger.warning(
                        f"Client error {status} {reason} for {method} {url}")
                    retries -= 1
                    if retries > 0:
                        wait_time = (self.max_retries - retries) * \
                            RETRY_WAIT_TIME
                        logger.info(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    continue

            except (ConnectionError, Timeout) as e:
                last_exception = e
                logger.warning(f"Connection error: {e}")
                retries -= 1
                if retries > 0:
                    wait_time = (self.max_retries - retries) * \
                        RETRY_WAIT_TIME  # Exponential backoff
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                continue
            except RequestException as e:
                last_exception = e
                logger.warning(f"Request error: {e}")
                retries -= 1
                if retries > 0:
                    wait_time = (self.max_retries - retries) * RETRY_WAIT_TIME
                    logger.info(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                continue
            except VerkadaTokenExpiredError as e:
                logger.error(f"Token expired: {e}")
                logger.info("Refreshing token")
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise e

        # If we get here, all retries failed
        if last_exception:
            if isinstance(last_exception, (ConnectionError, Timeout)):
                raise VerkadaConnectionError(
                    f"Failed to connect after {self.max_retries} retries: {last_exception}")
            else:
                raise last_exception
        else:
            raise VerkadaConnectionError(
                f"Request failed after {self.max_retries} retries")

    def request_pages(self, method, url, **kwargs):
        """
        Request pages from a Verkada API endpoint
        """
        response = self.request(method, url, **kwargs)
        return response

    def request_all_pages(self, method, url, keys, **kwargs):
        """
        Request all pages from a Verkada API endpoint
        """
        data = {}
        number_of_pages = 0
        next_page_token = None
        for k in keys:
            data[k] = []
        while next_page_token or number_of_pages == 0:
            number_of_pages += 1
            logging.info(f"Requesting page {next_page_token}")
            kwargs['params']['page_token'] = next_page_token
            response = self.request(method, url, **kwargs)
            next_page_token = response.json()['next_page_token']
            for k in keys:
                data[k].extend(response.json()[k])
        logger.info(f"Number of pages retrieved: {number_of_pages}")
        for k in keys:
            response.json()[k] = data[k]
        return MockResponse(response, data)


class VerkadaAPI():
    def __init__(self, api_key=None):
        self.api_key = None
        self.token = None
        self.session = VerkadaSession()
        self.timestamp = None

        if not api_key and not os.environ.get(VERKADA_ENVIRONMENT_VARIABLE_API_KEY):
            logger.error("API key not found")
            return
        self.api_key = api_key or os.environ.get(
            VERKADA_ENVIRONMENT_VARIABLE_API_KEY)
        

        self._readToken()
        try:
            if not self.token:
                token = self._refreshToken()
        except VerkadaTokenExpiredError as e:
            logger.error(f"Token expired during authentication: {e}")
            token = self._refreshToken()
            self.token = token
        except VerkadaConnectionError as e:
            logger.error(f"Connection error during authentication: {e}")
            raise
        except VerkadaAuthenticationError as e:
            logger.error(f"Authentication error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error during authentication: {e}")
            raise

    def _refreshToken(self):
        res = self.postLoginApiKeyViewV2()
        self.token = res.json()['token']
        self.timestamp = int(time.time())
        with open('token.json', 'w') as f:
            f.write(json.dumps({'token': self.token, 'timestamp': self.timestamp}))
        logger.info("Token refreshed and saved to token.json")

    def _readToken(self):
        logger.info("Reading token from token.json")
        if not os.path.exists('token.json'):
            logger.info("Token file not found, creating new token")
            self._refreshToken()
        else:
            with open('token.json', 'r') as f:
                token_data = json.load(f)
                self.token = token_data.get('token')
                self.timestamp = token_data.get('timestamp')
            if self.timestamp < int(time.time()) - DEFAULT_TOKEN_EXPIRATION_TIME * 60:
                logger.info("Token expired, refreshing token")
                self._refreshToken()

    def postLoginApiKeyViewV2(self):
        """
        API Tokens are required to make requests to any Verkada API endpoints with the exception of the Get Streaming Token endpoints, which requires a top-level API Key for authentication, as well as the Stream Footage (live or historical) API that requires a JSON Web Token (JWT).
        API Tokens inherit permissions from the top-level API key used to generate them and will be limited to that same permission scope. If the API Key used to generate an API Token only has Camera Read-Only permissions, then the associated API Token would only be authorized to call Camera GET endpoints.
        API Tokens are valid for 30 minutes and cannot be refreshed. Users will need to call the Get API Token endpoint again to retrieve a new Token if their previous one has expired. When making a call using an expired API Token, users will receive a 401 Authentication Error as well as the following error message:
        {'id': '0e2d', 'message': 'Token expired', 'data': None}
        """
        resource = f'/token'
        url = f"{DEFAULT_BASE_URL}{resource}"
        headers = {
            "x-api-key": f"{self.api_key}",
            "Content-Type": "application/json",
        }
        response = self.session.request('POST', url, headers=headers)
        return response

    def getAuditLogsViewV1(self,
                           start_time: Optional[int] = None,
                           end_time: Optional[int] = None,
                           page_size: Optional[int] = DEFAULT_PAGE_SIZE) -> Generator[Dict[str, Any], None, None]:
        """
        Generator function to retrieve all audit logs across multiple pages.

        Args:
            start_time (int, optional): Start of time range as Unix timestamp in seconds.
            end_time (int, optional): End of time range as Unix timestamp in seconds.
            page_size (int, optional): Number of items per page (1-200, default: 200).

        Yields:
            Individual audit log entries
        """
        query_params = {'start_time': start_time,
                        'end_time': end_time, 'page_size': page_size}
        clean_query_params = clean_params(query_params)
        resource = f'/core/v1/audit_log'
        url = f"{DEFAULT_BASE_URL}{resource}"
        headers = {
            "x-verkada-auth": f"{self.token}",
            "Content-Type": "application/json"
        }
        response = self.session.request_all_pages(
            'GET', url, ['audit_logs'], headers=headers, params=clean_query_params)
        return response

    def getNotificationsViewV1(self, 
                        start_time: Optional[int] = None,
                        end_time: Optional[int] = None,
                        include_image_url: Optional[bool] = False,
                        page_size: Optional[int] = DEFAULT_PAGE_SIZE,
                        notification_type: Optional[str] = None) -> Generator[Dict[str, Any], None, None]:
        """
        Convenience method to get all alerts of a specific type.
        
        Args:
            alert_type (str): Type of alert to retrieve (e.g., 'motion', 'person_of_interest')
            start_time (int, optional): Start of time range as Unix timestamp in seconds.
            end_time (int, optional): End of time range as Unix timestamp in seconds.
            include_image_url (bool, optional): Flag to include image URLs.
        
        Returns:
            List of all alerts of the specified type
        """
        query_params = {
            'start_time': start_time,
            'end_time': end_time,
            'include_image_url': include_image_url,
            'page_size': page_size,
            'notification_type': notification_type
        }
        clean_query_params = clean_params(query_params)
        resource = f'/cameras/v1/alerts'
        url = f"{DEFAULT_BASE_URL}{resource}"
        headers = {
            "x-verkada-auth": f"{self.token}",
            "Content-Type": "application/json"
        }
        response = self.session.request_all_pages(
            'GET', url, ['notifications'], headers=headers, params=clean_query_params)
        return response


if __name__ == "__main__":
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='Fetch Verkada audit logs')
    parser.add_argument('--start', type=int, help='Start time as Unix timestamp (required if --end is specified)')
    parser.add_argument('--end', type=int, help='End time as Unix timestamp (required if --start is specified)')
    args = parser.parse_args()

    # Validate that both start and end are provided together or neither
    if (args.start is None) != (args.end is None):
        parser.error('Both --start and --end must be specified together')

    # Get current time
    current_time = datetime.now()
    logger.info(f"Started at {current_time} ({current_time.timestamp()})")

    if args.start is not None and args.end is not None:
        # Use provided start and end times
        start_time = args.start
        end_time = args.end
        logger.info(f"Using provided time range")
    else:
        # Calculate end_time as the most recent 15-minute interval boundary
        # Round down to the nearest 15-minute mark
        minutes_past_interval = current_time.minute % CRON_INTERVAL_MINUTES
        end_time_dt = current_time.replace(second=0, microsecond=0) - timedelta(minutes=minutes_past_interval)
        end_time = int(end_time_dt.timestamp())

        # Calculate start_time as 15 minutes before the end_time
        start_time_dt = end_time_dt - timedelta(minutes=CRON_INTERVAL_MINUTES)
        start_time = int(start_time_dt.timestamp())

    logger.info(f"Fetching audit logs from {datetime.fromtimestamp(start_time)} ({start_time}) to {datetime.fromtimestamp(end_time)} ({end_time})")

    client = VerkadaAPI()
    # res = client.getAuditLogsViewV1()
    res = client.getAuditLogsViewV1(start_time=start_time, end_time=end_time)
    audit_logs = res.json()['audit_logs']
    for audit_log in audit_logs:
        if audit_log['event_name'] in INTERESTED_EVENTS:
            print(json.dumps(audit_log, indent=4))

    # res = client.getNotificationsViewV1()
    res = client.getNotificationsViewV1(start_time=start_time, end_time=end_time)
    notifications = res.json()['notifications']
    for notification in notifications:
        print(json.dumps(notification, indent=4))
