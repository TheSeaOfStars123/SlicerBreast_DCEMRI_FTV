'''
  @ Date: 2023/2/2 18:48
  @ Author: Zhao YaChen
'''
import cgi
import http.client
import json
import logging
import mimetypes
import os
import re
import ssl
import tempfile
from pathlib import Path
from urllib.parse import quote_plus, urlparse


class PhaseSelectClient:
    def __init__(self, server_url, tmpdir=None, client_id=None):
        self._server_url = server_url.rstrip("/").strip()
        self._tmpdir = tmpdir if tmpdir else tempfile.tempdir
        self._client_id = client_id

    def _update_client_id(self, params):
        if params:
            params["client_id"] = self._client_id
        else:
            params = {"client_id": self._client_id}
        return params

    def simple_info(self):
        selector = "/info/"
        status, response, _, _ = MONAILabelUtils.http_method("GET", self._server_url, selector)
        if status != 200:
            raise MONAILabelException(
                MONAILabelError.SERVER_ERROR, f"Status: {status}; Response: {response}", status, response
            )

        response = response.decode("utf-8") if isinstance(response, bytes) else response
        logging.debug(f"Response: {response}")
        return json.loads(response)

    def upload_image(self, image_in, image_id=None, tag="", params=None):
        selector = f"/datastore/?image={MONAILabelUtils.urllib_quote_plus(image_id)}"
        if tag:
            selector += f"&tag={MONAILabelUtils.urllib_quote_plus(tag)}"

        files = {"file": image_in}
        params = self._update_client_id(params)
        fields = {"params": json.dumps(params) if params else "{}"}

        status, response, _, _ = MONAILabelUtils.http_multipart("PUT", self._server_url, selector, fields, files)
        if status != 200:
            raise MONAILabelException(
                MONAILabelError.SERVER_ERROR,
                f"Status: {status}; Response: {response}",
            )

        response = response.decode("utf-8") if isinstance(response, bytes) else response
        logging.debug(f"Response: {response}")
        return json.loads(response)

class MONAILabelError:
    RESULT_NOT_FOUND = 1
    SERVER_ERROR = 2
    SESSION_EXPIRED = 3
    UNKNOWN = 4


class MONAILabelException(Exception):
    def __init__(self, error, msg, status_code=None, response=None):
        self.error = error
        self.msg = msg
        self.status_code = status_code
        self.response = response


class MONAILabelUtils:
    @staticmethod
    def http_method(method, server_url, selector, body=None):
        logging.debug(f"{method} {server_url}{selector}")

        parsed = urlparse(server_url)
        path = parsed.path.rstrip("/")
        selector = path + "/" + selector.lstrip("/")
        logging.debug(f"URI Path: {selector}")

        parsed = urlparse(server_url)
        if parsed.scheme == "https":
            logger.debug("Using HTTPS mode")
            # noinspection PyProtectedMember
            conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, context=ssl._create_unverified_context())
        else:
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port)

        headers = {}
        if body:
            if isinstance(body, dict):
                body = json.dumps(body)
                content_type = "application/json"
            else:
                content_type = "text/plain"
            headers = {"content-type": content_type, "content-length": str(len(body))}

        conn.request(method, selector, body=body, headers=headers)
        return MONAILabelUtils.send_response(conn)

    @staticmethod
    def http_upload(method, server_url, selector, fields, files):
        logging.debug(f"{method} {server_url}{selector}")

        url = server_url.rstrip("/") + "/" + selector.lstrip("/")
        logging.debug(f"URL: {url}")

        files = [("files", (os.path.basename(f), open(f, "rb"))) for f in files]
        response = requests.post(url, files=files) if method == "POST" else requests.put(url, files=files, data=fields)
        return response.status_code, response.text, None

    @staticmethod
    def http_multipart(method, server_url, selector, fields, files):
        logging.debug(f"{method} {server_url}{selector}")

        content_type, body = MONAILabelUtils.encode_multipart_formdata(fields, files)
        headers = {"content-type": content_type, "content-length": str(len(body))}

        parsed = urlparse(server_url)
        path = parsed.path.rstrip("/")
        selector = path + "/" + selector.lstrip("/")
        logging.debug(f"URI Path: {selector}")

        if parsed.scheme == "https":
            logger.debug("Using HTTPS mode")
            # noinspection PyProtectedMember
            conn = http.client.HTTPSConnection(parsed.hostname, parsed.port, context=ssl._create_unverified_context())
        else:
            conn = http.client.HTTPConnection(parsed.hostname, parsed.port)

        conn.request(method, selector, body, headers)
        return MONAILabelUtils.send_response(conn, content_type)

    @staticmethod
    def send_response(conn, content_type="application/json"):
        response = conn.getresponse()
        logging.debug(f"HTTP Response Code: {response.status}")
        logging.debug(f"HTTP Response Message: {response.reason}")
        logging.debug(f"HTTP Response Headers: {response.getheaders()}")

        response_content_type = response.getheader("content-type", content_type)
        logging.debug(f"HTTP Response Content-Type: {response_content_type}")

        if "multipart" in response_content_type:
            if response.status == 200:
                form, files = MONAILabelUtils.parse_multipart(response.fp if response.fp else response, response.msg)
                logging.debug(f"Response FORM: {form}")
                logging.debug(f"Response FILES: {files.keys()}")
                return response.status, form, files, response.headers
            else:
                return response.status, response.read(), None, response.headers

        logging.debug("Reading status/content from simple response!")
        return response.status, response.read(), None, response.headers

    @staticmethod
    def save_result(files, tmpdir):
        for name in files:
            data = files[name]
            result_file = os.path.join(tmpdir, name)

            logging.debug(f"Saving {name} to {result_file}; Size: {len(data)}")
            dir_path = os.path.dirname(os.path.realpath(result_file))
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

            with open(result_file, "wb") as f:
                if isinstance(data, bytes):
                    f.write(data)
                else:
                    f.write(data.encode("utf-8"))

            # Currently only one file per response supported
            return result_file

    @staticmethod
    def encode_multipart_formdata(fields, files):
        limit = "----------lImIt_of_THE_fIle_eW_$"
        lines = []
        for (key, value) in fields.items():
            lines.append("--" + limit)
            lines.append('Content-Disposition: form-data; name="%s"' % key)
            lines.append("")
            lines.append(value)
        for (key, filename) in files.items():
            lines.append("--" + limit)
            lines.append(f'Content-Disposition: form-data; name="{key}"; filename="{filename}"')
            lines.append("Content-Type: %s" % MONAILabelUtils.get_content_type(filename))
            lines.append("")
            with open(filename, mode="rb") as f:
                data = f.read()
                lines.append(data)
        lines.append("--" + limit + "--")
        lines.append("")

        body = bytearray()
        for line in lines:
            body.extend(line if isinstance(line, bytes) else line.encode("utf-8"))
            body.extend(b"\r\n")

        content_type = "multipart/form-data; boundary=%s" % limit
        return content_type, body

    @staticmethod
    def get_content_type(filename):
        return mimetypes.guess_type(filename)[0] or "application/octet-stream"

    @staticmethod
    def parse_multipart(fp, headers):
        fs = cgi.FieldStorage(
            fp=fp,
            environ={"REQUEST_METHOD": "POST"},
            headers=headers,
            keep_blank_values=True,
        )
        form = {}
        files = {}
        if hasattr(fs, "list") and isinstance(fs.list, list):
            for f in fs.list:
                logger.debug(f"FILE-NAME: {f.filename}; NAME: {f.name}; SIZE: {len(f.value)}")
                if f.filename:
                    files[f.filename] = f.value
                else:
                    form[f.name] = f.value
        return form, files

    @staticmethod
    def urllib_quote_plus(s):
        return quote_plus(s)
