---
name: ig-repurpose
description: >-
  Turn one long asset - a YouTube video, podcast, livestream, newsletter, blog
  post or client call - into a week of reels and carousels. Use when the user
  says "repurpose this", "turn this into reels", "I have a video/podcast/
  transcript", "cut this up", or pastes something long and wants it on
  Instagram.
---

# ig-repurpose

## 한국어 사용 규칙 (이 파일의 다른 지시보다 우선)

1. **모든 결과는 자연스러운 한국어 구어체로 쓴다.** 대본, 캡션, 댓글, DM, 리포트, 설명 전부 해당한다. 번역투 말고 실제로 말하듯이 쓴다.
2. **점수를 매기는 파이썬 도구는 한국어에 쓰지 않는다.** `hookscore.py`, `beats.py`, `detect.py`, 그리고 `swipe.py`의 훅 점수는 영어 단어 기준이라 한국어 문장을 제대로 세지 못한다. 대신 이 SKILL.md에 적힌 기준을 직접 읽고 판단해서, 숫자 대신 **"통과"** 또는 **"고칠 점 + 이유"**로 알려준다. 이 파일의 예시 출력에 나오는 숫자 점수(예: `86 STRONG`, `human score 81 PASS`)도 한국어 결과에서는 이 형식으로 바꿔서 보여준다.
3. **클로드가 기준표로 직접 매기는 점수는 그대로 보여준다.** 예를 들어 `/ig-profile`의 `rubric.json` 100점 채점처럼, 도구가 아니라 클로드가 기준표를 보고 매기는 점수는 숫자로 보여준다.


One good long asset contains four to six posts. Most people extract one and
throw the rest away.

## Input

A transcript, an article, a newsletter, a script, a call summary, a livestream.
If the user gives a URL and this session has a transcript tool, use it;
otherwise ask them to paste. Read the whole thing before extracting anything.

If the source is a video the user owns, ask for the file too. A Reel built on
their own footage beats one built on their own words read again.

## Extract, do not summarise

A summary of a video is not a Reel. Nobody wants the summary. Go through the
asset and pull out the things that stand alone:

| pull | what it is |
| --- | --- |
| **Claims** | every sentence that would start an argument |
| **Numbers** | every figure, cost, duration, percentage |
| **Stories** | every moment with a person, a scene and a cost |
| **Mechanisms** | every "the way this actually works is..." |
| **Mistakes** | every admission of something that went wrong |
| **Lines** | every sentence already quotable as-is |

List what you found, with counts, before writing anything. If the asset yields
fewer than four items, it is thin, and four posts squeezed out of it will be
thin too. Say that.

## Then pick the format per extract

Not everything is a Reel.

- **Claim, mistake, story** to a Reel. They need a voice and a face.
- **Mechanism, numbered list** to a carousel. They need to be re-read.
- **A quotable line** to a story frame, not a post.

## Then build the week

Each extract becomes one post and each post stands completely on its own. The
viewer has not seen the source and never will. Never write "as I said in my
latest video". The post is the thing.

Assign a hook formula from `ig-reel/hooks.json` to each and vary them. Five
posts from one source with the same hook shape reads as a content mill, because
it is one.

If the source is the user's own video, **use the actual footage**. The clip
where they said the thing, with the real reaction in it, beats a re-record
every time. Cut on the sentence, not on the breath.

Order across the week so the strongest claim goes first, the story lands
midweek, and the mechanism goes last, when the people who liked the earlier
ones are watching for it.

## Output

```
SOURCE: "Why we killed discovery calls" (42 min podcast, 8,900 words)

FOUND  5 claims, 9 numbers, 3 stories, 4 mechanisms, 2 mistakes, 7 quotable lines

WEEK
TUE  REEL      #2  Negative Command  Stop running discovery calls
                                     use the 14:20 clip, he laughs at the end
WED  CAROUSEL  Job B caption         The 4-question form that replaced the call
FRI  REEL      #21 Mid-Sentence      "...and he asked for a refund nine days later"
SUN  REEL      #5  Time Collapse     Six hours a week back, one deleted link

Say "write Tuesday" and I will draft it.
```

Then draft on request, one at a time, each through `/ig-reel` and `/ig-human`.
Do not dump four finished scripts at once. They will all sound the same and the
user will shoot none of them.
