---
name: reels-auto-edit
description: 사용자의 릴스(세로 숏폼) 영상을 편집규칙집대로 자동 편집한다. 사용자가 영상을 주거나 폴더에 넣고 "편집해줘", "릴스 편집", "컷 편집해줘", "자막 넣어줘"라고 할 때 사용. 결과에 대한 피드백("자막이 작아", "배경음이 커")을 규칙에 반영할 때, "이 릴스처럼 편집해줘"+링크로 스타일을 바꿀 때도 사용.
---

# 릴스 자동 편집

사용자에게 하는 말은 **전부 쉬운 한국어**로, 짧게. 끝날 때까지 묻지 말고 진행한다.

## 0. 작업 폴더 찾기 + 준비
- 작업 폴더 = `engine/reels.py` 와 `style.json` 이 있는 폴더. 현재 열린 폴더 → 그 아래 `reels_work/` → `/home/user/Wondermom-young` 순서로 찾는다.
- 아래에서 `$W` 는 작업 폴더, `$PY` 는 `$W/.venv/bin/python`.
- `$PY` 가 없거나 패키지가 없으면 `bash $W/setup.sh` 를 먼저 실행한다(파이썬·Node·ffmpeg·글꼴·브라우저·받아쓰기 모델 설치). 설치 직후 명령이 안 잡히면 전체 경로로 실행한다.
- 폴더 경로에 한글이 있으면 일부 도구가 파일을 못 연다 → 프로그램은 영상을 `jobs/<영문이름>/` 으로 옮겨서 처리한다(자동).
- 편집 전에 `편집규칙집.md` 맨 아래 "피드백 기록"을 읽고 그 내용을 지킨다(숫자는 style.json 에 이미 들어 있음).

## 1. 편집 순서 (반드시 이 순서)

### ① 받아쓰기
```
$PY $W/engine/reels.py find                      # 영상 찾기 (사용자가 경로를 안 줬을 때)
$PY $W/engine/reels.py transcribe "<영상경로>" [--vocab "고유명사1, 고유명사2"]
```
- faster-whisper large-v3-turbo, 단어 단위 시간. 단어 시작 시각은 소리 크기로 다시 잡는다(자동).
- 결과: `jobs/<이름>/words.md`(받아쓰기 표: 단어 번호·시간·음량), `words.json`, `plan.json`(규칙 기반 초안).
- 영상이 없으면 사용자에게 한 줄: "10초짜리 영상 하나를 찍어서 이 폴더에 넣어 주세요" 하고 기다린다.

### ② 교정 대본 = plan.json 직접 작성 (가장 중요 — 네가 직접 읽고 판단)
`words.md` 를 처음부터 끝까지 **직접 읽고** `plan.draft.json` 초안을 참고해 `plan.json` 을 고쳐 쓴다.
할 수 있는 건 **지우기뿐**. 말의 내용·말투·어순은 절대 바꾸지 않는다.

지울 것 (`delete` 에 단어 번호):
- 더듬은 곳("그 그", "이, 이거"), 군말(음, 어, 그…), 말하다 끊고 다시 한 곳
- 같은 문장을 여러 번 읽었으면: 마지막 테이크들 중 **음량 큰 쪽(카메라 보고 크게 읽은 쪽)** 만 남기고 나머지 테이크 전부
- 속삭이며 대본 보는 테이크(음량이 평소보다 8dB 이상 작음, "작음(속삭임?)" 메모)
- 단어 없는 숨소리·입소리는 원래 남지 않는다(단어 기준으로 자름)

`fix`: 잘못 들린 단어의 **자막 표기만** 고친다. `{"12": "한울김치"}` (앞 공백 유지가 필요하면 " 한울김치")
`highlight_words`: 이 영상만의 강조(노란색) 키워드. `cta_keyword`: 댓글 키워드.
`hook`: 첫 문장에서 뽑은 상단 제목 2줄(줄당 12자 안팎, 말한 단어로만), `highlight` 핵심 단어, `emoji` 감정 이모지 1개.

`sentences`: 남길 문장들을 **원래 순서대로**. 각 문장 = `{"from": 첫 단어번호, "to": 끝 단어번호, "layout": "face"|"split", "role": ..., "scene": {...}, "text": "확인용 문장"}`
- `layout: "face"`(얼굴 크게)는 **첫 문장(role "hook")**, **강조·반전 문장 1~2개(role "emphasis")**, **댓글 유도 첫 문장(role "cta")** 뿐. 나머지는 전부 `"split"`.
- 위아래 화면(split)이 전체 길이의 **70~85%** 가 되게 한다(모자라면 프로그램이 얼굴 문장 뒷부분을 그래픽으로 돌림).
- split 문장마다 `scene` 을 **문장 내용을 읽고 직접** 고른다. 말하는 내용을 그대로 그림으로:

| template | 언제 | 데이터 |
|---|---|---|
| `connect` | 두 앱/사람/물건 연결 | `left:{label,icon}`, `right:{label,icon}`, `caption`, `kicker`, `badge` |
| `countup` | 숫자가 나올 때 | `value`, `suffix`(년/원/%…), `prefix`, `label`, `sub`, `from`, `bar`(0~1) |
| `chat` | 입력·질문·메시지 | `messages:[{from:"me"|"bot", text}]`, `typing`(입력창에 쳐지는 글), `title` |
| `checklist` | 여러 개 나열·단계 | `title`, `items:[…]`(최대 5) |
| `beforeafter` | 전/후, 예전/지금 비교 | `title`, `before:{title,items}`, `after:{title,items}` (나쁨=빨강, 좋음=초록) |
| `comment_dm` | 댓글 달면 DM | `comment`(키워드), `dm`, `user`, `title` |
| `photos` | 후기·실물 사진 | `images:["assets/reviews/review1.jpg", …]`(최대 4), `caption`, `title` |
| `statement` | 그 밖의 핵심 한 줄 | `text`, `kicker`, `sub` |

- 문구는 그 문장에서 말한 단어로 짧게(카드 한 줄 12자 안팎). `**단어**` 로 앵버 강조.
- **모르는 숫자·명령어·주소·이름은 지어내지 말고** 값에 `null` 또는 `"?"` → 화면에서 흐리게 가려진다.
- 말하는 순간에 맞춰 요소가 나오게 하려면 `cue_words: [단어번호, …]`(요소 순서대로).
- 같은 장면을 다음 문장까지 이어가려면 다음 문장 `"scene": "continue"`.
- 사용자의 후기 사진은 `assets/reviews/` 에 있다(한울김치 선물 후기 5장).

### ③④⑤ 렌더 (컷 편집 → 자막·강조·제목·모션그래픽·효과음·배경음 → mp4)
```
$PY $W/engine/reels.py render <이름>
```
- 출력: `output/<이름>_edited.mp4`. 중간 재압축 없이 마지막에 한 번만 고화질 저장.
- `bgm/` 폴더에 곡이 있으면 그 곡, 없으면 직접 만든 잔잔한 비트. 효과음도 직접 만든 소리.

## 2. 스스로 검수 (반드시)
```
$PY $W/engine/reels.py check <이름> --autofix
```
1. 완성본을 다시 받아써서 자막과 비교 → 다른 곳이 진짜 오타면 `fix` 로 표기 수정(말은 그대로).
2. 경계 클릭음 / 단어 끝 잘림(`--autofix` 가 `extend_end` 로 늘려줌) / 말 중간 긴 무음 / 검은 화면 / 멈춘 화면 → 고친다.
3. `jobs/<이름>/contact.jpg`(프레임 모아보기)를 **Read 로 직접 열어 보고**: 자막이 얼굴·제목·그래픽을 가리지 않는지, 그래픽 글자가 잘리거나 너무 작지 않은지, 모션그래픽이 70% 이상인지 확인.
4. 고친 게 있으면 `render` → `check` 다시. 문제 없을 때까지.
5. 사용자에게 짧게 보고: 원본 → 완성 길이, 지운 말 개수, 고친 것, 완성 파일 위치. (클라우드 세션이면 SendUserFile 로 mp4 와 contact.jpg 를 보내준다.)

## 3. 피드백 반영 ("자막이 작아", "배경음이 커" 등)
뜻을 숫자로 바꿔 style.json 과 규칙집에 함께 남긴다. 예:
```
$PY $W/engine/reels.py feedback --note "자막이 작아" --rule "자막 크기 70→80px" --set subtitle.font_size=80
$PY $W/engine/reels.py feedback --note "배경음이 커" --rule "배경음을 목소리보다 22dB 아래로" --set bgm.below_voice_db=22
```
- `--set` 은 여러 번 가능(점 경로). 규칙집 "피드백으로 추가된 규칙"과 맨 아래 "피드백 기록" 표에 자동 기록 → 다음 편집부터 자동 반영.
- 숫자로 안 되는 피드백(예: "그래픽이 심심해")은 규칙집 해당 절을 직접 고치고 `feedback --note … --rule …` 로 기록, 필요하면 `engine/scenes/scene.html` 템플릿을 고친다.
- 방금 영상에 바로 다시 적용해 달라면 `render` → `check` 다시.

자주 쓰는 키: `subtitle.font_size`, `subtitle.outline`, `subtitle.y_face`, `subtitle.max_chars`, `title.font_size`, `emphasis.pop_min_gap`, `emphasis.zoom`, `zoom.cut_to`, `cut.max_pause`, `bgm.below_voice_db`, `bgm.duck_db`, `sfx.gain_db`, `loudness.target_lufs`, `layout.split_ratio_min`, `graphics.accent`.

## 4. "이 릴스처럼 편집해줘" + 링크
```
$PY $W/engine/reels.py ref "<링크>"
```
- 영상을 받아(yt-dlp) `refs/<시각>/` 에 컷 횟수, 말 속도, 음량, 프레임 모아보기(`contact_first15s.jpg`, `contact_all.jpg`)를 만든다.
- 모아보기를 **직접 열어 보고** 자막 크기·색·위치·테두리, 제목 스타일, 그래픽 비율·색, 확대 정도, 컷 속도를 읽어 style.json 과 편집규칙집.md 를 그 스타일에 맞게 고친다. 바꾼 내용은 `feedback --note "<링크> 스타일 적용" --rule … --set …` 로 기록.
- 인스타 다운로드가 막히면 사용자에게 "그 릴스를 휴대폰에 저장해서 이 폴더에 넣어 주세요"라고 안내한다.

## 사용자가 직접 해야 하는 일이 생기면
컴퓨터를 잘 모르는 사람도 따라 하게 "어디를 눌러서 → 무엇을 붙여넣는지" 한 단계씩 번호로 적는다.
