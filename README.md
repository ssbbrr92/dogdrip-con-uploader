# DogDrip.Con Uploader

개드립넷의 개드립콘 등록 화면에 이미지와 게시글 정보를 자동으로 배치하는 Windows용 비공식 도구입니다.

폴더 안의 이미지를 파일 이름 또는 수정된 날짜로 정렬한 뒤 전용 Chrome/Edge 프로필로 열린 등록 페이지에 채웁니다. 게시글 제목, 판매 포인트, 본문, 태그도 함께 입력할 수 있습니다. 최종 등록 버튼은 사용자가 브라우저에서 직접 눌러야 합니다.

## 주요 기능

- 폴더의 PNG, JPG, JPEG, GIF, WebP 파일을 최대 50개까지 배치
- 파일 이름·수정된 날짜 기준의 정방향/역방향 정렬
- 제목, 판매 포인트, 본문, 태그 자동 입력
- WYSIWYG 편집기에서 링크, 가로줄, 원격 이미지 삽입·수정 지원
- 이미지 자동 미리보기, 크기 설정, 원본 비율 맞춤 지원
- 배지 형태의 태그 입력 지원
- 사이트 입력 필드 이름이 변경될 때 `dogdrip-con-uploader.ini`에서 매칭 수정
- 로그인 상태를 유지하는 전용 Chrome/Edge 프로필 사용

## 다운로드 및 사용

일반 사용자는 GitHub Releases에서 최신 EXE를 내려받아 실행하면 됩니다. 상세 절차는 [사용법](docs/사용법.txt)을 참고하세요. v1.1.1의 변경 내용은 [릴리즈 노트](docs/RELEASE_NOTES_v1.1.1.md)에서 확인할 수 있습니다.

1. 이미지 폴더를 선택합니다.
2. 게시글 정보와 배치 순서를 입력합니다.
3. 등록 페이지를 열고 로그인한 뒤 `이미지와 내용 채우기`를 누릅니다.
4. 브라우저에서 결과를 확인하고 최종 등록 버튼을 직접 누릅니다.

전용 브라우저 프로필에는 로그인 정보가 남을 수 있으므로 공용 PC에서는 사용하지 않는 것을 권장합니다. 프로필은 EXE 옆의 `dogdrip-con-browser-profile` 폴더에 생성됩니다.

## 소스 실행

Windows와 Python 3.12 기준입니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python src\app.py
```

## 테스트

```powershell
python -m unittest discover -s tests -v
```

## EXE 빌드

```powershell
.\build.ps1
```

빌드 결과는 `dist\DogDrip.Con-Uploader-v1.1.1.exe`에 생성됩니다.

## 배포 관련 주의

이 프로그램은 개드립넷과 공식적으로 제휴하거나 보증받은 제품이 아닙니다. 포함된 개드립넷 프로필 아이콘은 별도 재배포 허가를 확인하지 못했으므로 공개 배포 전 권리자의 사용·재배포 허가를 확인하는 것이 안전합니다. 자세한 내용은 [배포·라이선스 점검](docs/배포-라이선스-점검.txt)을 참고하세요.

이 프로그램은 개드립넷(dogdrip.net)의 개드립콘 기능을 활용한 무료·비공식 소프트웨어입니다.  
개드립넷의 명칭·서비스·관련 이미지에 대한 권리는 개드립넷(dogdrip.net)에 있습니다.
