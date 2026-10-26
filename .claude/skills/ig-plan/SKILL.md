---
name: ig-plan
description: >-
  Build the week on Instagram - what to post, which format, when, and who to
  engage with. Use when the user says "plan my week", "what should I post",
  "content calendar", "I have nothing to post about", or wants a posting
  schedule and an engagement list.
---

# ig-plan

## 한국어 사용 규칙 (이 파일의 다른 지시보다 우선)

1. **모든 결과는 자연스러운 한국어 구어체로 쓴다.** 대본, 캡션, 댓글, DM, 리포트, 설명 전부 해당한다. 번역투 말고 실제로 말하듯이 쓴다.
2. **점수를 매기는 파이썬 도구는 한국어에 쓰지 않는다.** `hookscore.py`, `beats.py`, `detect.py`, 그리고 `swipe.py`의 훅 점수는 영어 단어 기준이라 한국어 문장을 제대로 세지 못한다. 대신 이 SKILL.md에 적힌 기준을 직접 읽고 판단해서, 숫자 대신 **"통과"** 또는 **"고칠 점 + 이유"**로 알려준다. 이 파일의 예시 출력에 나오는 숫자 점수(예: `86 STRONG`, `human score 81 PASS`)도 한국어 결과에서는 이 형식으로 바꿔서 보여준다.
3. **클로드가 기준표로 직접 매기는 점수는 그대로 보여준다.** 예를 들어 `/ig-profile`의 `rubric.json` 100점 채점처럼, 도구가 아니라 클로드가 기준표를 보고 매기는 점수는 숫자로 보여준다.


The control room. Everything else in this pack executes; this decides what gets
executed. Run it once a week, on the same day.

## Input

If `~/.claude/instagram/voice.md`, `swipe.md` and `log.md` exist, read them.
The swipe file is the user's own evidence from `/ig-viral` about which formulas
are landing in their niche right now, and it outranks anything in this file.
The log stops the plan repeating a theme from the last fortnight.

If they do not exist, ask for four things and write them down:

1. What the user sells, and to whom.
2. The three or four themes they want to be known for.
3. What actually happened this week: a client call, a number, a mistake, a
   thing they built, an argument they had. This is where posts come from.
4. Ten accounts worth being visible to.

## What to post

Four to five posts a week, and at least three of them Reels. Reels are the only
format on Instagram that reliably reaches people who do not follow the account.
Carousels go deep with the people who already do. Stories are daily and are
planned separately.

Mix across the week, never two of the same type back to back:

| type | share | job |
| --- | --- | --- |
| **Proof** | 1 per week | something that happened, with a number. Reel. |
| **Teach** | 1 to 2 per week | one thing the viewer can do today. Reel or carousel. |
| **Opinion** | 1 per week | a position that could lose you followers. Reel. |
| **Story** | 1 per fortnight | a scene with a cost. Reel. |
| **Offer** | 1 per fortnight | what you sell, said plainly, no apology. Carousel or stories. |

For each slot give: the theme, the specific angle from what actually happened
this week, the format, and the hook formula number from `ig-reel/hooks.json`.
Not a topic, an angle. "AI" is not a plan. "The proposal we lost because the
draft had an em dash in it" is a Reel.

## When to post

Post when the user's audience is awake and not at work. For most consumer
audiences that is early evening local time; for a business audience, early
morning.

But say this plainly: **the hour matters far less than the first two seconds.**
Instagram will keep showing a Reel for days if it performs, and will bury a
well-timed one that does not. If the user is optimising posting times before
their hooks work, they are polishing the wrong thing, and you should say so.

Anchor times to the audience's timezone, not the user's, if those differ.

## The engagement round, which is not optional

20 minutes a day, before posting, not after. Build a list of 10:

- **5 reach** - accounts with an audience the user wants, where a good comment
  gets seen. Comment early, before the thread is 200 deep.
- **3 peers** - same size, same field. This is the group that reciprocates.
- **2 buyers** - people who could actually buy. Comment for weeks before any
  DM, and never pitch in a comment.

Hand the list to `/ig-comment`.

## Output

```
WEEK OF SEP 15

MON  engage only  (20 min, list below)
TUE  7:30pm  REEL      PROOF    #5  Time Collapse   - 5hr proposal to 20 min
WED  stories only + engage
THU  7:00pm  CAROUSEL  TEACH    Job B caption       - the 4-slide clause breakdown
FRI  7:30pm  REEL      OPINION  #2  Negative Command - stop doing discovery calls
SAT  -
SUN  6:00pm  REEL      STORY    #21 Mid-Sentence    - the refund email

STORIES  every day, 3 to 5 frames, question box on Thursday.

ENGAGE  (5 reach / 3 peers / 2 buyers)
  ...

Say "write Tuesday" and I will draft it.
```

Write the plan to `~/.claude/instagram/plan.md` so the other skills can read
it. Nothing is scheduled or posted anywhere. This is a plan and the user runs
it.
