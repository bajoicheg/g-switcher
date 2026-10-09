"""GitHub host HTTP transport; redirects never forward authorization to storage."""
import io
import json
import os
import urllib.error
import urllib.request
import zipfile

REPO = 'bajoicheg/g-switcher'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(path, method='GET', data=None, binary=False):
    url = 'https://api.github.com/repos/' + REPO + '/' + path
    request = urllib.request.Request(url, method=method,
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
                 'Accept': 'application/vnd.github+json', 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=30) as response:
            body = response.read()
    except urllib.error.HTTPError as error:
        if error.code not in {301, 302, 303, 307, 308} or not binary:
            # Do not chain raw transport exceptions into logs.
            raise RuntimeError('GitHub API request failed: status=' + str(error.code)) from None
        location = error.headers['Location']
        if not location.startswith('https://'):
            raise ValueError('Storage redirect must use HTTPS')
        with urllib.request.urlopen(urllib.request.Request(location), timeout=60) as response:
            body = response.read()
    except (OSError, urllib.error.URLError):
        raise RuntimeError('GitHub API transport unavailable') from None
    return body if binary else (None if not body else json.loads(body))


def archive(artifact_id):
    return api('actions/artifacts/' + str(artifact_id) + '/zip', binary=True)


def member(data, suffix):
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.endswith(suffix)]
        if len(names) != 1:
            raise ValueError('Exact archive member is ambiguous or missing')
        return z.read(names[0])
