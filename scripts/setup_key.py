from getpass import getpass

from investment_copilot.secrets import save_openai_api_key

print("OpenAI API key를 Windows Credential Manager에 저장합니다.")
print("입력 내용은 화면에 표시되지 않습니다.")
key = getpass("OPENAI_API_KEY: ").strip()
if not key:
    raise SystemExit("빈 key라서 저장하지 않았습니다.")
save_openai_api_key(key)
print("저장 완료.")
