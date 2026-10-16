#!/usr/bin/env python3
"""把二升三、三升四孩子看得见的题面改成能读出口的话。知识点仍留给分组，不出现在标题里。"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "references/education-stage-starters.json"
QUOTE = re.compile(r"[“\"']([^”\"']+)[”\"']")
ADD = re.compile(r"(\d+)\s*\+\s*(\d+)")
SUB = re.compile(r"(\d+)\s*-\s*(\d+)")
MUL = re.compile(r"(\d+)\s*[×x]\s*(\d+)")
DIV = re.compile(r"(\d+)\s*÷\s*(\d+)")
METER = re.compile(r"(\d+)\s*米")
HOUR = re.compile(r"(\d+)\s*小时(?:\s*(\d+)\s*分)?")
RECT = re.compile(r"长\s*(\d+).*宽\s*(\d+)")
SQUARE = re.compile(r"边长\s*(\d+)")
BLANK = re.compile(r"一（\s*）([^”\"。？]*)")

THINGS = ("糖", "贴纸", "星星", "豆子", "积木", "玻璃珠")
POLY = {
    "edu34-lang-02": ("假期", "假"),
    "edu34-lang-14": ("银行", "行"),
    "edu34-lang-15": ("音乐", "乐"),
    "edu34-lang-16": ("长大", "长"),
    "edu34-lang-17": ("重量", "重"),
    "edu34-lang-18": ("好学", "好"),
}
PERSONIFY = {
    "edu34-lang-04": ("树叶在风中跳舞。", "会跳舞的人", ["会跳舞的人", "一块石头", "一道算术题", "一声雷"], "跳舞是人会做的事，这里把树叶当成小人。"),
    "edu34-lang-24": ("小河唱着歌向前流。", "会唱歌的人", ["会唱歌的人", "一块砖", "一把尺", "一张桌子"], "唱歌是人会做的事，这里把小河当成小人。"),
    "edu34-lang-25": ("星星在眨眼。", "会眨眼的人", ["会眨眼的人", "一块橡皮", "一支粉笔", "一扇门"], "眨眼是人会做的事，这里把星星当成小人。"),
    "edu34-lang-26": ("风儿轻轻地抚摸着草地。", "会用手的人", ["会用手的人", "一块铁", "一把椅子", "一本作业"], "抚摸是人会做的事，这里把风当成小人。"),
}

ICONS = {
    "开心": "😊", "快乐": "😊", "高兴": "😊", "难过": "😢", "伤心": "😢", "害怕": "😨",
    "漂亮": "🌸", "美丽": "🌸", "丑陋": "🤢", "迅速": "⚡", "快速": "⚡", "快捷": "⚡", "缓慢": "🐢",
    "马上": "⏱️", "立刻": "⏱️", "认真": "📝", "仔细": "🔍", "马虎": "🙃", "粗心": "🙃",
    "勤奋": "💪", "努力": "💪", "懒惰": "😴", "勇敢": "🦸", "英勇": "🦸", "胆小": "🐣",
    "安静": "🤫", "宁静": "🤫", "热闹": "🎉", "喧哗": "📢",
    "枝": "✏️", "本": "📕", "朵": "🌸", "匹": "🐴", "条": "🐟", "辆": "🚗", "封": "✉️",
    "铅笔": "✏️", "书": "📕", "花": "🌸", "鱼": "🐟", "汽车": "🚗", "马": "🐴",
    "猫": "🐱", "狗": "🐶", "鸟": "🐦", "熊猫": "🐼", "兔子": "🐰", "老虎": "🐯", "大象": "🐘", "猴子": "🐵",
    "苹果": "🍎", "香蕉": "🍌", "橙子": "🍊", "水": "💧", "太阳": "☀️", "月亮": "🌙",
    "红色": "🔴", "蓝色": "🔵", "绿色": "🟢", "黄色": "🟡",
    "学校": "🏫", "医院": "🏥", "公园": "🌳", "商店": "🛒", "教室": "🏫", "车站": "🚉",
    "图书馆": "📚", "厨房": "🍳", "卧室": "🛏️",
    "钢笔": "🖊️", "包": "🎒", "尺子": "📏", "橡皮": "🧽",
    "星期一": "1️⃣", "星期二": "2️⃣", "星期三": "3️⃣", "星期四": "4️⃣",
    "星期五": "5️⃣", "星期六": "6️⃣", "星期日": "7️⃣",
    "洗手": "🧼", "吃饭": "🍚", "开门": "🚪",
}


def quoted(text: str) -> str:
    match = QUOTE.search(text or "")
    return match.group(1) if match else ""


def thing(item_id: str) -> str:
    return THINGS[sum(ord(char) for char in item_id) % len(THINGS)]


def icons_for(options: list[str] | None) -> dict[str, str]:
    if not options:
        return {}
    found = {option: ICONS[option] for option in options if option in ICONS}
    return found


def set_voice(row: dict, title: str, prompt: str, mission: str, story: str = "", options: list[str] | None = None, answer: str | None = None, explanation: str | None = None) -> None:
    row["title"] = title
    row["prompt"] = prompt
    row["mission"] = mission
    if story:
        row["story"] = story
    if options is not None:
        row["options"] = options
        extra = icons_for(options)
        if extra:
            row["option_icons"] = extra
    elif row.get("options"):
        extra = icons_for(list(row["options"]))
        if extra:
            row["option_icons"] = extra
    if answer is not None:
        row["answer"] = answer
    if explanation is not None:
        row["explanation"] = explanation


def rewrite_synonym(row: dict) -> None:
    word = quoted(row.get("prompt") or "") or quoted(row.get("title") or "")
    answer = str(row.get("answer") or "")
    if not word or word == answer:
        parts = QUOTE.findall(str(row.get("explanation") or ""))
        if len(parts) >= 2:
            word = parts[0] if parts[0] != answer else parts[1]
        elif not word:
            word = "这个词"
    set_voice(
        row,
        f"{word}还可以怎么说",
        f"「{word}」还可以怎么说？",
        "找出意思最像的那个词",
        f"有人刚说了「{word}」。",
    )


def rewrite_antonym(row: dict) -> None:
    word = quoted(row.get("prompt") or "")
    if not word:
        word = "这个词"
    set_voice(
        row,
        f"{word}的对面是谁",
        f"「{word}」的对面是哪一个？",
        "找出意思相反的那个",
        f"「{word}」站在这边。",
    )


def rewrite_measure(row: dict) -> None:
    noun = ""
    match = BLANK.search(row.get("prompt") or "")
    if match:
        noun = match.group(1).strip()
    if not noun:
        noun = "这个东西"
    set_voice(
        row,
        f"{noun}怎么数",
        f"一只手里有一____{noun}，空里填哪个最合适？",
        f"帮{noun}找到自己的量词",
        f"要数{noun}了。",
    )


def rewrite_punct(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    if "问号" in prompt:
        title, ask = "哪一句在提问", "哪一句是在问人？"
    elif "感叹" in prompt:
        title, ask = "哪一句在惊叹", "哪一句听起来最惊喜？"
    elif "逗号" in prompt:
        title, ask = "哪一句停得对", "哪一句中间的停顿最自然？"
    elif "句号" in prompt:
        title, ask = "哪一句说完了", "哪一句是平平说完的一句话？"
    elif "引号" in prompt:
        title, ask = "哪一句在转述", "哪一句把别人说的话框起来了？"
    else:
        title, ask = "哪一句标点最顺", "哪一句读起来最顺口？"
    set_voice(row, title, ask, "选读起来最顺的那一句")


def rewrite_order(row: dict) -> None:
    set_voice(row, "哪一句最顺口", "哪一句读起来最像人话？", "把乱序的话排顺")


def rewrite_poem_author(row: dict) -> None:
    line = quoted(row.get("prompt") or "")
    prompt = str(row.get("prompt") or "")
    if "下一句" in prompt and line:
        set_voice(row, "下一句是哪句", f"「{line}」的下一句是哪一句？", "把诗接完", f"先听这半句：{line}")
    elif "出自" in prompt and line:
        set_voice(row, "这句出自哪首", f"「{line}」是哪一首诗里的？", "给诗句找家", f"有人念：{line}")
    elif line:
        set_voice(row, "这是谁写的", f"「{line}」，是谁写的？", "给诗句找到作者", f"有人念：{line}")
    else:
        set_voice(row, "诗里在说什么", prompt.replace("主要", "").replace("告诉我们", "是在说"), "听懂诗在说什么")


def rewrite_extract(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    body = prompt.replace("短文：", "").strip()
    if "？" in body:
        story, _, question = body.rpartition("。")
        if not question:
            story, question = "", body
        else:
            question = question.strip()
            story = (story + "。").strip()
    else:
        story, question = body, "刚才那段话里，最重要的是什么？"
    title = question.replace("？", "").replace("?", "")[:10] or "听完选一选"
    set_voice(row, title, question if question.endswith("？") else f"{question}？", "从刚才的话里找出答案", story)


def rewrite_expand(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    topic = "这件事"
    for word in ("小猫", "下雨", "跑步", "笑", "风", "读书"):
        if word in prompt:
            topic = word
            break
    set_voice(row, "哪句更像一幅画", f"哪一句把「{topic}」写得更能看见？", "选更清楚的那一句")


def rewrite_polyphone(row: dict) -> None:
    item_id = str(row.get("item_id") or "")
    if item_id in POLY:
        word, char = POLY[item_id]
    else:
        prompt = str(row.get("prompt") or "")
        parts = QUOTE.findall(prompt)
        word = next((part for part in parts if len(part) > 1), parts[0] if parts else "")
        char = next((part for part in parts if len(part) == 1), "")
        if not char and word:
            char = word[-1]
        if not word:
            word = char or "这个字"
    set_voice(row, f"{word}里的{char}怎么读", f"「{word}」里的「{char}」，选一个读音。", "给这个字选对声音", f"黑板上写着「{word}」。")


def rewrite_rhetorical(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    if "意思" in prompt or "接近" in prompt:
        line = quoted(prompt)
        set_voice(row, "这句话其实在说", f"「{line or '这句话'}」其实是在说什么？", "听懂提醒")
    elif "不是反问" in prompt:
        set_voice(row, "哪一句只是在说话", "哪一句只是平平地说，没有在提醒别人？", "分开真问和假问")
    elif "哪一句是反问" in prompt:
        set_voice(row, "哪一句在认真提醒", "哪一句其实是在提醒，不是真的不知道？", "听出藏起来的意思")
    else:
        set_voice(row, "哪一句其实在说对", "哪一句听起来像问句，其实是在说“当然该这样”？", "选那句认真的提醒")


def rewrite_personify(row: dict) -> None:
    item_id = str(row.get("item_id") or "")
    if item_id in PERSONIFY:
        line, answer, options, why = PERSONIFY[item_id]
        short = line.replace("。", "").replace("“", "").replace("”", "")[:8]
        set_voice(row, short, f"{line}这句话把谁当成了会动的小人？", "找出被当成小人的东西", line, options, answer, why)
        return
    prompt = str(row.get("prompt") or "")
    if "哪一句" in prompt:
        set_voice(row, "哪句把东西当成人", "哪一句把不会说话的东西，写成了会笑、会动的小人？", "找出那句最像童话的")
        return
    line = quoted(prompt) or prompt.split("主要")[0].strip("。 ")
    if str(row.get("answer")) in {"拟人", "比喻", "排比", "设问", "夸张", "反问", "对比"}:
        answer = str((row.get("options") or [""])[0] or "会动的人")
        # keep existing kid options if already rewritten
        if any("人" in str(option) for option in row.get("options") or []):
            set_voice(row, "谁被当成了小人", f"{line}这句话把谁当成了小人？", "找出被当成小人的东西", line)
        else:
            options = ["会动的小人", "一块石头", "一道算术题", "一声雷"]
            set_voice(row, "谁被当成了小人", f"{line}这句话把谁当成了小人？", "找出被当成小人的东西", line, options, "会动的小人", "这里把不会说话的东西写成了人。")
        return
    line = quoted(prompt) or prompt.split("。")[0]
    short = line.replace("“", "").replace("”", "")[:8] or "谁被当成了小人"
    set_voice(row, short, f"{line}。这句话把谁当成了会动的小人？", "找出被当成小人的东西", line)


def rewrite_sick(row: dict) -> None:
    set_voice(row, "哪一句最顺口", "哪一句读起来最顺口？", "把别扭的话改顺")


def rewrite_summary(row: dict) -> None:
    set_voice(row, "这段在干什么", "刚才这几句，主要在说谁在干什么？", "用一句话说完这段")


def rewrite_observe(row: dict) -> None:
    set_voice(row, "哪句是亲眼看见的", str(row.get("prompt") or "").replace("更有用", "更像亲眼看见").replace("更应该", "更该"), "记下眼睛看见的")


def rewrite_add(row: dict) -> None:
    match = ADD.search(row.get("prompt") or "")
    if not match:
        return
    left, right = match.group(1), match.group(2)
    name = thing(row["item_id"])
    set_voice(row, f"再放进 {right} 颗", f"盒子里有 {left} 颗{name}，又放进 {right} 颗。现在一共多少颗？", "数一数合起来有多少", f"先有 {left} 颗{name}。")


def rewrite_sub(row: dict) -> None:
    match = SUB.search(row.get("prompt") or "")
    if not match:
        return
    left, right = match.group(1), match.group(2)
    name = thing(row["item_id"])
    set_voice(row, f"拿走 {right} 颗", f"盘子里有 {left} 颗{name}，吃掉 {right} 颗。还剩多少颗？", "数一数还剩多少", f"先有 {left} 颗{name}。")


def rewrite_mul(row: dict) -> None:
    match = MUL.search(row.get("prompt") or "")
    if not match:
        return
    left, right = match.group(1), match.group(2)
    name = thing(row["item_id"])
    set_voice(row, f"{left} 盘{name}", f"{left} 个小盘，每盘 {right} 颗{name}。一共多少颗？", "一盘一盘加起来")


def rewrite_div(row: dict) -> None:
    match = DIV.search(row.get("prompt") or "")
    if not match:
        return
    left, right = match.group(1), match.group(2)
    name = thing(row["item_id"])
    set_voice(row, f"分给 {right} 人", f"{left} 颗{name}，平均分给 {right} 个小朋友。每人几颗？", "每人分到同样多")


def rewrite_length(row: dict) -> None:
    match = METER.search(row.get("prompt") or "")
    meters = match.group(1) if match else ""
    if meters:
        set_voice(row, f"{meters} 米有多长", f"一根 {meters} 米的绳子，等于多少厘米？", "换一把更细的尺来量")
    else:
        set_voice(row, "换一把尺", str(row.get("prompt") or ""), "用厘米说出来")


def rewrite_avg(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    set_voice(row, "每人分到几个", prompt.replace("平均分给", "平分给"), "每人一样多")


def rewrite_minutes(row: dict) -> None:
    match = HOUR.search(row.get("prompt") or "")
    if match:
        hours = match.group(1)
        mins = match.group(2) or "0"
        if mins == "0":
            set_voice(row, f"{hours} 小时是多久", f"{hours} 小时等于多少分钟？", "用分钟说出来")
        else:
            set_voice(row, f"{hours} 小时再加 {mins} 分", f"{hours} 小时 {mins} 分，一共多少分钟？", "先算整点，再加剩下的")
        return
    set_voice(row, "过了多少分钟", str(row.get("prompt") or "").replace("等于多少分钟", "一共多少分钟"), "数一数分钟")


def rewrite_peri(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    rect = RECT.search(prompt)
    square = SQUARE.search(prompt)
    if rect:
        set_voice(row, "镜框一圈多长", f"一个长 {rect.group(1)} 厘米、宽 {rect.group(2)} 厘米的镜框，走一圈是多少厘米？", "把四条边加起来")
    elif square:
        set_voice(row, "方框一圈多长", f"一个边长 {square.group(1)} 厘米的方框，走一圈是多少厘米？", "四条边一样长")
    else:
        set_voice(row, "走一圈多长", prompt.replace("周长", "走一圈"), "把四条边加起来")


def rewrite_time_clock(row: dict) -> None:
    set_voice(row, "现在几点了", str(row.get("prompt") or "").replace("是几点", "到了几点"), "看看钟走了多久")


def rewrite_apply(row: dict) -> None:
    set_voice(row, "一共有多少", str(row.get("prompt") or ""), "一堆一堆加起来")


def rewrite_estimate(row: dict) -> None:
    set_voice(row, "最靠近谁", str(row.get("prompt") or "").replace("通常看成", "最靠近").replace("下面哪个整百数", "哪个整百数"), "找离它最近的整百")


def rewrite_english_word(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    word = ""
    match = re.search(r"\b([A-Za-z]{2,})\b", prompt)
    if match:
        word = match.group(1)
    if "星期" in prompt and word:
        set_voice(row, f"{word} 是周几", f"{word} 是星期几？", "给这一天找到中文")
        return
    if word:
        set_voice(row, f"哪一个是 {word}", f"{word} 是什么？选你认识的那个。", f"给 {word} 找到朋友")
        return
    set_voice(row, "选对的那一个", prompt, "看图选一选")


def rewrite_letter(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    letters = re.findall(r"[A-Z]", prompt)
    hole = "、".join(letters[:3]) if letters else "字母"
    set_voice(row, "缺了哪个字母", f"{hole} 中间少了谁？", "把字母排队")


def rewrite_greet(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    if "Good morning" in prompt:
        set_voice(row, "早上怎么回", "别人对你说 Good morning，你回哪一句？", "回一句早上的招呼")
    elif "晚上" in prompt:
        set_voice(row, "晚上说哪句", "晚上见面，说哪一句更合适？", "选晚上的招呼")
    elif "How are you" in prompt:
        set_voice(row, "你好吗怎么回", "别人问 How are you? 回哪一句？", "回一句我很好")
    elif "分别" in prompt or "Goodbye" in prompt:
        set_voice(row, "再见说哪句", "要分开了，说哪一句？", "选一句再见")
    elif "帮了你" in prompt:
        set_voice(row, "谢谢说哪句", "别人帮了你，说哪一句？", "把谢谢说出来")
    elif "Hello" in prompt:
        set_voice(row, "Hello 是什么意思", "Hello 更接近哪一句中文？", "给 Hello 找到中文")
    else:
        set_voice(row, "这时说哪句", prompt, "选一句能说出口的")


def rewrite_be(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    lead = prompt.split("___")[0].strip() or "I"
    set_voice(row, f"{lead} 后面跟谁", prompt.replace("横线处应填什么？", "选一个填进去。").replace("应填？", "选一个填进去。").replace("横线处填什么？", "选一个填进去。"), "给这句话找对的小词")


def rewrite_plural(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    set_voice(row, "不止一个怎么说", prompt.replace("应填？", "选哪个？").replace("应该搭配哪一个？", "选哪个？").replace("横线处应填什么？", "选哪个？"), "一样东西变多了")


def rewrite_prep(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    set_voice(row, "它在哪里", prompt.replace("表示", "是说").replace("应选？", "选哪个？").replace("较合适的是？", "选哪个？"), "说出东西在哪儿")


def rewrite_wh(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    if "名字" in prompt:
        set_voice(row, "怎么问名字", "想问别人叫什么，说哪一句？", "问出名字")
    elif "年龄" in prompt:
        set_voice(row, "怎么问几岁", "想问别人几岁，说哪一句？", "问出年纪")
    elif "地点" in prompt:
        set_voice(row, "怎么问在哪", "东西不见了，问在哪，说哪一句？", "问出地方")
    elif "谁" in prompt:
        set_voice(row, "怎么问是谁", "想问那是谁，说哪一句？", "问出是谁")
    elif "做" in prompt:
        set_voice(row, "怎么问在干什么", "想问别人正在干什么，说哪一句？", "问出动作")
    else:
        set_voice(row, "哪一句在提问", prompt, "选能问出口的那句")


def rewrite_polite(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    set_voice(row, "这时说哪句更甜", prompt.replace("合适回答是？", "回哪一句？").replace("较合适的回应是？", "回哪一句？").replace("更合适的是？", "说哪一句？"), "选更有礼貌的那句")


def rewrite_en_extract(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    if "." in prompt:
        sentence, _, question = prompt.partition(".")
        sentence, question = sentence.strip(), question.strip()
        set_voice(row, "刚才那句在说什么", f"{sentence}. {question or '选对的那个。'}", "从刚才的英文里找答案", sentence)
    else:
        set_voice(row, "刚才那句在说什么", prompt, "从英文里找答案")


def rewrite_saying(row: dict) -> None:
    line = quoted(row.get("prompt") or "")
    if line:
        set_voice(row, "这句话在提醒什么", f"「{line}」是在提醒我们什么？", "听懂老话", f"墙上写着：{line}")
    else:
        set_voice(row, "这句话在提醒什么", str(row.get("prompt") or "").replace("主要", "").replace("强调什么", "是在说什么"), "听懂老话")


def rewrite_virtue(row: dict) -> None:
    word = quoted(row.get("prompt") or "")
    if word:
        set_voice(row, f"{word}在夸什么", f"「{word}」这个故事，在夸哪种好？", "听懂故事在夸谁")
    else:
        set_voice(row, "这个故事在夸什么", str(row.get("prompt") or ""), "听懂故事在夸谁")


def rewrite_method(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    if "生字" in prompt:
        set_voice(row, "遇到生字怎么办", "读着读着碰到不认识的字，怎么办？", "选能继续读下去的办法")
    elif "写了谁" in prompt:
        set_voice(row, "先看谁在干什么", "想知道短文写了谁，先看什么？", "抓住人和事")
    elif "依据" in prompt or "做题" in prompt:
        set_voice(row, "答案去哪找", "题目问完了，答案应该去哪找？", "回到刚才那段话")
    elif "长句子" in prompt:
        set_voice(row, "长句子怎么读", "一句话太长了，怎么办？", "拆开来读")
    elif "题目" in prompt:
        set_voice(row, "题目该写什么", "给短文起名字，名字应该怎样？", "让人一看就知道写了什么")
    elif "图表" in prompt or "数字" in prompt:
        set_voice(row, "图和数字在说什么", "看见图和数字，更该干什么？", "读懂它在说明什么")
    elif "说明" in prompt or "关键词" in prompt:
        set_voice(row, "说明文先抓什么", prompt.replace("主要是为了？", "是为了什么？"), "先抓住最有用的话")
    else:
        set_voice(row, "怎么读更清楚", prompt, "选更好用的读法")


def rewrite_seq(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    if "最先" in prompt or "第一步" in prompt:
        set_voice(row, "谁先谁后", prompt, "排出先做的那一步")
    else:
        set_voice(row, "事情怎么往下走", prompt.replace("主要采用什么顺序", "是按什么往下说").replace("这是？", "这是按什么说的？").replace("这更像？", "更像哪一种？"), "看事情怎么往下走")


def rewrite_metaphor(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    line = quoted(prompt)
    if "比作" in prompt and line:
        set_voice(row, "把它比成了什么", f"{line}把它比成了什么？", "找出那个比喻")
    elif "哪一句" in prompt:
        set_voice(row, "哪句在打比方", "哪一句把一个东西比成了另一个东西？", "找出打比方的那句")
    else:
        set_voice(row, "把它比成了什么", prompt.replace("把", "").replace("比作什么？", "被比成了什么？"), "找出那个比喻")


def rewrite_feeling(row: dict) -> None:
    set_voice(row, "他现在什么心情", str(row.get("prompt") or "").replace("最可能是？", "更像哪种心情？").replace("更可能是？", "更像哪种心情？"), "看他的样子猜心情")


def rewrite_idiom(row: dict) -> None:
    word = quoted(row.get("prompt") or "")
    if word:
        set_voice(row, f"{word}在说什么", f"「{word}」是在说哪种情况？", "听懂这个老故事")
    else:
        set_voice(row, "这个成语在说什么", str(row.get("prompt") or ""), "听懂这个老故事")


def rewrite_after(row: dict) -> None:
    set_voice(row, "读完可以怎么说", str(row.get("prompt") or "").replace("最合适的复盘方式是？", "更该怎么说？").replace("更合适的是？", "更该怎么说？"), "用自己的话说出来")


def rewrite_reason(row: dict) -> None:
    rewrite_extract(row)
    row["title"] = row["title"] or "为什么会这样"
    if not str(row.get("prompt") or "").endswith("？"):
        return
    if "为什么" not in row["prompt"] and "谁" not in row["prompt"]:
        row["prompt"] = row["prompt"].replace("？", "，是因为什么？") if False else row["prompt"]


def rewrite_theme(row: dict) -> None:
    set_voice(row, "取个最像的名字", str(row.get("prompt") or "").replace("最合适的题目是？", "取哪个名字最像？"), "给这段话取个名字")


def rewrite_science(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    prompt = prompt.replace("通常更可能是？", "更像哪一类？").replace("正确做法是？", "该怎么办？").replace("更应该？", "更该怎么做？").replace("主要有什么作用？", "最重要是干什么？").replace("一个常见作用是？", "常常是干什么的？")
    title = str(row.get("title") or "")
    if re.search(r"(科学|观察|实验|光影|植物|交通|温度|材料|规律|根 |水 |用电|环保|图形|分类|数列)", title):
        title = (quoted(prompt) or prompt.split("，")[0].split("？")[0])[:12] or "看一看选一选"
    set_voice(row, title if not re.match(r"^(科学|光影|植物|交通|温度|材料|规律|根|水|用电|环保|图形|分类|数列)", title) else "看一看选一选", prompt, "先看，再选")


def rewrite_pattern(row: dict) -> None:
    prompt = str(row.get("prompt") or "")
    set_voice(row, "下一个是谁", prompt.replace("横线处应填？", "下一个是谁？").replace("应填？", "下一个是谁？"), "找出重复的队伍")


HANDLERS = {
    "近义词": rewrite_synonym,
    "近义词辨析": rewrite_synonym,
    "反义词": rewrite_antonym,
    "量词搭配": rewrite_measure,
    "标点符号": rewrite_punct,
    "句子语序": rewrite_order,
    "古诗积累": rewrite_poem_author,
    "信息提取": rewrite_extract,
    "句子扩写": rewrite_expand,
    "多音字": rewrite_polyphone,
    "反问句": rewrite_rhetorical,
    "拟人": rewrite_personify,
    "拟人感知": rewrite_personify,
    "病句修改": rewrite_sick,
    "段意概括": rewrite_summary,
    "观察表达": rewrite_observe,
    "诗句理解": rewrite_saying,
    "两位数进位加法": rewrite_add,
    "三位数加法": rewrite_add,
    "两位数退位减法": rewrite_sub,
    "三位数减法": rewrite_sub,
    "表内乘法": rewrite_mul,
    "两位数乘一位数": rewrite_mul,
    "表内除法": rewrite_div,
    "两位数除一位数": rewrite_div,
    "长度单位换算": rewrite_length,
    "平均分问题": rewrite_avg,
    "时间单位换算": rewrite_minutes,
    "长方形周长初步": rewrite_peri,
    "长方形周长": rewrite_peri,
    "时间计算": rewrite_time_clock,
    "乘法应用": rewrite_apply,
    "估算": rewrite_estimate,
    "字母顺序": rewrite_letter,
    "基础词汇": rewrite_english_word,
    "动物词汇": rewrite_english_word,
    "学习用品词汇": rewrite_english_word,
    "场所词汇": rewrite_english_word,
    "星期词汇": rewrite_english_word,
    "日常问候": rewrite_greet,
    "be 动词": rewrite_be,
    "be动词": rewrite_be,
    "名词复数": rewrite_plural,
    "方位介词": rewrite_prep,
    "特殊疑问句": rewrite_wh,
    "礼貌表达": rewrite_polite,
    "短句信息提取": rewrite_en_extract,
    "名句理解": rewrite_saying,
    "古诗主题": rewrite_saying,
    "传统美德": rewrite_virtue,
    "阅读方法": rewrite_method,
    "说明文阅读": rewrite_method,
    "原因提取": rewrite_reason,
    "事情顺序": rewrite_seq,
    "叙述顺序": rewrite_seq,
    "主题概括": rewrite_theme,
    "比喻": rewrite_metaphor,
    "人物情感": rewrite_feeling,
    "成语寓意": rewrite_idiom,
    "读后感": rewrite_after,
    "光和影": rewrite_science,
    "植物生长条件": rewrite_science,
    "植物结构": rewrite_science,
    "水的状态": rewrite_science,
    "对比实验": rewrite_science,
    "分类": rewrite_science,
    "交通安全": rewrite_science,
    "温度与变化": rewrite_science,
    "材料特性": rewrite_science,
    "材料用途": rewrite_science,
    "环保分类": rewrite_science,
    "用电安全": rewrite_science,
    "生活安全": rewrite_science,
    "简单数列": rewrite_pattern,
    "倍数规律": rewrite_pattern,
    "重复规律": rewrite_pattern,
    "平面图形": rewrite_science,
}


WORKSHEET = re.compile(r"(语文|数学|英语|阅读|观察|科学|近义|量词|标点|语序|古诗|提取|反义|扩写|加法|减法|乘法|除法|长度|平均分|时间|周长|字母|词义|问候|动物|用品|短句|复数|名句|说明|美德|顺序|比喻|心情|成语|读后|光影|植物|交通|温度|材料|规律|根 |水 |用电|环保|图形|分类|数列|问句|方位|礼貌|词汇|句型|计算|修辞|人物|多音|反问|拟人|病句|段意|诗句|场所|星期|应用|估算|实验) ?\d+$")


def rewrite_item(row: dict) -> None:
    handler = HANDLERS.get(str(row.get("knowledge_point") or ""))
    if handler:
        handler(row)
    elif WORKSHEET.search(str(row.get("title") or "")):
        prompt = str(row.get("prompt") or "")
        set_voice(row, (quoted(prompt) or prompt.split("？")[0])[:12] or "选一选", prompt, "先看，再选")
    extra = icons_for(list(row.get("options") or []))
    if extra:
        row["option_icons"] = extra


def main() -> None:
    data = json.loads(ROOT.read_text(encoding="utf-8"))
    changed = 0
    leftover = []
    for stage in data.get("stages", []):
        if stage.get("stage_id") not in {"primary-transition-2-to-3", "primary-transition-3-to-4"}:
            continue
        for items in stage.get("modules", {}).values():
            for row in items:
                if row.get("kind") != "question":
                    continue
                rewrite_item(row)
                changed += 1
                if WORKSHEET.search(str(row.get("title") or "")):
                    leftover.append(f"{row.get('item_id')}:{row.get('title')}")
    ROOT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"rewrote {changed} items, leftover_titles={len(leftover)}")
    if leftover:
        print("\n".join(leftover[:20]))


if __name__ == "__main__":
    main()
