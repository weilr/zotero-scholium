"""Numeric fidelity warnings must preserve values, signs and percentages."""

import pytest

from zotero_scholium import cli


def translation_warnings(source, translated):
    return cli.check_translations([
        {"type": "highlight", "pageLabel": "1", "text": source, "comment": translated}
    ])


@pytest.mark.parametrize(("source", "translated"), [
    ("Accuracy increased by 5%.", "准确率提高 50%。"),
    ("Memory is 1.5 GB.", "内存为 15 GB。"),
    ("The value is -5.", "数值为 5。"),
    ("The value is 5.", "数值为 -5。"),
    ("The value is 5%.", "数值为 5。"),
    ("The value is 5.", "数值为 5%。"),
    ("The value is +5.", "数值为 -5。"),
    ("Memory is 15 GB.", "内存为 1.5 GB。"),
    ("The value is .5.", "数值为 5。"),
    ("We use CIFAR10.", "使用 CIFAR100。"),
    ("We use model15.", "使用 dataset15。"),
    ("We use GPT-4.", "使用 GPT-40。"),
    ("We use GPT-4.1.", "使用 GPT-4.10。"),
    ("We use 500k samples.", "使用 500 万个样本。"),
    ("Memory is 1.5GB.", "内存为 1 GB。"),
    ("Memory is 1.5GB.", "内存为 15 GB。"),
    ("Memory is 1.5 GB.", "内存为 1.5 MB。"),
    ("Memory is 1.5GB.", "内存为 1.5MB。"),
    ("Time is 5ms.", "时间为 5 s。"),
    ("The value is 1.5widgets.", "数值为 1。"),
    ("Latency is 5 ms.", "延迟为5秒。"),
    ("The whole MP-­3 took 8 min.", "整个 MP-4 用时 8 min。"),
    ("It uses a 2.4-GHz access point.", "它使用 2.4 MHz 接入点。"),
    ("Values of 10-20 ms.", "取值 10-20 s。"),
])
def test_warns_when_translation_changes_number_meaning(source, translated):
    warnings = translation_warnings(source, translated)
    assert warnings, (source, translated)
    assert any("not present" in reason for reason in warnings[0]["reasons"])


@pytest.mark.parametrize(("source", "translated"), [
    ("We use 500k samples.", "使用 50 万个样本。"),
    ("We use 500,000 samples.", "使用 50 万个样本。"),
    ("Memory is 1.5 GB.", "内存为 1.50 GB。"),
    ("The value is -5.", "数值为 −5。"),
    ("The value is +5.", "数值为 5。"),
    ("Accuracy increased by 5%.", "准确率提高 5 ％。"),
    ("The value is .5.", "数值为 0.5。"),
    ("We use CIFAR10.", "使用 CIFAR10。"),
    ("We use GPT-4.", "使用 GPT-4。"),
    ("We use GPT-4.1.", "使用 GPT-4.1。"),
    ("We use 5-10 samples.", "使用 5–10 个样本。"),
    ("The value is 1e-3.", "数值为 0.001。"),
    ("The value is 0.001.", "数值为 1e-3。"),
    ("Memory is 1.5GB.", "内存为 1.5 GB。"),
    ("Memory is 1.5 GB.", "内存为 1.50GB。"),
    ("Time is 5ms.", "时间为 5 ms。"),
    ("Time is 5 ms.", "时间为 5ms。"),
    ("Latency is 5 ms.", "延迟为5毫秒。"),
    ("Latency is 5 s.", "延迟为5秒。"),
    ("Latency is 5 us.", "延迟为5微秒。"),
    ("Latency is 5 μs.", "延迟为5微秒。"),
    ("Latency is 5 ns.", "延迟为5纳秒。"),
    # PDF text: soft hyphens, Unicode hyphens, a hyphen between a number and its unit
    ("The whole MP-­3 took 8 min.", "整个 MP-3 用时 8 min。"),
    ("Phase MP‑1 maps the area.", "阶段 MP-1 绘制该区域地图。"),
    ("It uses a 2.4-GHz access point.", "它使用 2.4 GHz 接入点。"),
    ("A 5‑ms delay.", "5 ms 的延迟。"),
])
def test_accepts_equivalent_numeric_notation(source, translated):
    assert translation_warnings(source, translated) == []


def test_large_scientific_exponents_stay_compact():
    tokens = cli._tokens("1e1000000")
    assert max(map(len, tokens)) < 40
    assert translation_warnings("The value is 1e1000000.", "数值为 10e999999。") == []
