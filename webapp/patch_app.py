with open('app.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_mock = "print(f\"\\n[MOCK SMS] Sent OTP {otp} to Driver Phone {data.get('driver_phone', 'None')}\\n\")"

new_real = """phone = data.get('driver_phone')
        if phone:
            try:
                import requests
                # We use Textbelt for free real-time testing SMS (1 per day limit without key)
                resp = requests.post('https://textbelt.com/text', data={
                    'phone': phone, 
                    'message': f'Skandha WMS: Your Dock Assignment OTP is {otp}', 
                    'key': 'textbelt'
                })
                print("[REAL SMS API]", resp.json())
            except Exception as e:
                print("SMS Error:", e)"""

content = content.replace(old_mock, new_real)

with open('app.py', 'w', encoding='utf-8') as f:
    f.write(content)
