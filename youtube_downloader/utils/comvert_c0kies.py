from utils.auth import YouTubeAuthenticator
auth = YouTubeAuthenticator()
cookies=input('Enter the path to your browser cookies JSON file (e.g., www.youtube.com.json): ').strip()
result = auth.convert_json_cookies_to_netscape(cookies)
print(f'Conversion result: {result}')
if result:
    import os
    print(f'File exists: {os.path.exists(result)}')
    if os.path.exists(result):
        with open(result, 'r') as f:
            content = f.read()
            lines = content.split('\n')
            print(f'Lines in file: {len(lines)}')
            print('First few lines:')
            for i, line in enumerate(lines[:10]):
                if line.strip():
                    print(f'{i+1}: {line.strip()[:100]}...')
