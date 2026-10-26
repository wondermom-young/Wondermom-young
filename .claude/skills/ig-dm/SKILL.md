---
name: ig-dm
description: >-
  Write Instagram DMs that get replies - the keyword delivery, the first
  message to someone who engaged, the collab pitch, and the two follow-ups. Use
  when the user says "DM this person", "what do I send them", "outreach
  message", "how do I follow up", "pitch this brand", or is reaching out to
  someone specific.
---

# ig-dm

## 한국어 사용 규칙 (이 파일의 다른 지시보다 우선)

1. **모든 결과는 자연스러운 한국어 구어체로 쓴다.** 대본, 캡션, 댓글, DM, 리포트, 설명 전부 해당한다. 번역투 말고 실제로 말하듯이 쓴다.
2. **점수를 매기는 파이썬 도구는 한국어에 쓰지 않는다.** `hookscore.py`, `beats.py`, `detect.py`, 그리고 `swipe.py`의 훅 점수는 영어 단어 기준이라 한국어 문장을 제대로 세지 못한다. 대신 이 SKILL.md에 적힌 기준을 직접 읽고 판단해서, 숫자 대신 **"통과"** 또는 **"고칠 점 + 이유"**로 알려준다. 이 파일의 예시 출력에 나오는 숫자 점수(예: `86 STRONG`, `human score 81 PASS`)도 한국어 결과에서는 이 형식으로 바꿔서 보여준다.
3. **클로드가 기준표로 직접 매기는 점수는 그대로 보여준다.** 예를 들어 `/ig-profile`의 `rubric.json` 100점 채점처럼, 도구가 아니라 클로드가 기준표를 보고 매기는 점수는 숫자로 보여준다.


Instagram DMs are the only place on the platform where money actually changes
hands, and they are also where most accounts burn the goodwill their content
earned. The difference is entirely about who moved first.

## The three kinds of DM, and only three are worth writing

**1. The reply to a hand raised.** They commented the keyword, answered the
poll, replied to a story, or saved and asked. They moved first. This is 90% of
the DMs worth sending and it converts because it is not outreach.

**2. The warm approach.** Someone whose posts the user has genuinely been
commenting on for weeks. There is a shared thread of conversation already.

**3. The collab or brand pitch.** A specific proposal to a specific account,
with a reason it is them.

Everything else is cold DMing strangers, which is what everybody else does, and
it is why reply rates sit where they do. If the user is asking for a cold
sequence, say plainly that it is the lowest-yield thing they could do with the
same hour, and offer the alternative: comment on those ten accounts for two
weeks first. Then write it if they still want it.

## Before writing, get the specifics

Ask in one batched question:

1. **Who** - handle, what they do, and what they posted or did that started
   this.
2. **The trigger** - the actual reason to message today. A keyword they
   commented, a story they replied to, a post they published. Not "they fit the
   ICP".
3. **What the user wants** - a conversation, a sale, a collab, a referral. Be
   honest internally, even if the message does not lead with it.

If there is no trigger, there is no message. Say so.

## The keyword delivery

The most common DM in this pack and the easiest to ruin. They commented one
word. They are expecting the thing. So:

```
{their name}, here it is: {the thing, or the link}.

{one line on how to use it}

{one question they can answer in four words}
```

Send the thing **first**, in message one, with no gate. A keyword post that
delivers a "before I send it, can I ask what you do?" is a bait and switch and
it is remembered. The question at the end is what starts the conversation, and
it is optional for them.

Automated keyword replies are a supported feature for professional accounts,
through Instagram's own tools or an approved partner. Using that is fine.
Sending unsolicited bulk DMs is not, and it is the fastest route to a
restricted account.

## The first message to someone warm

- **Two to four sentences.** A screen of text is a delete.
- **Reference the specific thing.** The comment, the post, the reply. In their
  words.
- **Give before asking.** A number, a template, a name, an answer.
- **One ask, small.** "Worth a quick call?" beats "let me walk you through the
  platform".
- **No link and no calendar in message one.** It reads as a funnel because it
  is one.
- **No voice note to a stranger.** It is a great tool and it is for people who
  already know the user's voice.

## The collab pitch

Four lines, in this order: what you have watched them do, the specific idea,
what they get, what you need from them. A collab post lands on both grids and
reaches both audiences, which is the strongest single growth mechanic on
Instagram that does not involve paying anybody. Pitch it as that and be
concrete about who does what.

## Follow-ups

Two. That is the number.

- **+4 days** - add something new. Never "just bumping this". If there is
  nothing new, there is no follow-up.
- **+10 days** - the close-the-loop message. Say you will stop, and mean it.
  This one gets a surprising share of the total replies, because it removes the
  pressure.

Then stop. A third converts nobody and costs the relationship.

## Never

- Never automate outreach DMs, and never use a tool that sends on a schedule to
  people who did not interact. It violates Instagram's Terms of Use and
  restricts the account.
- Never fabricate having watched something, a mutual, or a shared anything.
- Never open with "Hey! Quick question" and then not ask a question.
- Never send the pitch in the same message as the compliment.

## Output

The message, the character count, and the two follow-ups with the day each
goes out, all run through `/ig-human`. The user sends every one of them by
hand, or through their own approved automation for keyword replies only.
