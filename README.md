# 직원 출퇴근 체크 웹앱 - 온라인 DB 버전

이 버전은 PostgreSQL 같은 온라인 데이터베이스를 사용하도록 바뀐 배포용 버전입니다.

## 기본 계정
- 관리자 PIN: `1234`
- 직원 PIN: `0000`
- 직원 13명 자동 생성

## Render 배포
이 폴더 전체를 GitHub 저장소에 올린 뒤 Render에서 Blueprint 또는 Web Service로 배포하면 됩니다.

`render.yaml`이 포함되어 있어 Blueprint 배포가 가장 쉽습니다.

## 중요
배포 후 Render 환경변수에서 `ADMIN_PIN`을 원하는 번호로 바꾸세요.
`SECRET_KEY`는 Render가 자동 생성하도록 설정되어 있습니다.
