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



# Highlights from real runs whose faithful translations were reported: PDF text loses superscripts and
# subscripts (10⁻³ becomes 10−3, L² becomes L2, CM² becomes "CM 2"), writes mathematical italic letters
# (Λ𝑜𝑢𝑡), puts a space after a thousands separator, and the comments keep names and citations in English.
@pytest.mark.parametrize(("source", "translated"), [
    ("However, since the function space L2(Ω) is infinite-dimensional.", "然而，由于函数空间 L<sup>2</sup>(Ω) 是无穷维的。"),
    ("Fourier attention requires a complexity of O(CM 2), while Galerkin attention requires a complexity of O(C2M).",
     "Fourier attention 的复杂度为 O(CM<sup>2</sup>)，而 Galerkin attention 的复杂度为 O(C<sup>2</sup>M)。"),
    ("Our model is trained with an initial learning rate of 1 × 10−3.", "模型的初始学习率为 1 × 10<sup>−3</sup>。"),
    ("We train on a resolution of 852 and test with resolutions from 432 to 4212.", "用 85² 的数据训练，在 43² 到 421² 的分辨率上测试。"),
    ("The bound is rather loose (≈8 × 103 here).", "这个界相当宽松（这里约 8 × 10<sup>3</sup>）。"),
    ("The Reynolds numbers are high (105−107).", "雷诺数很高（10<sup>5</sup>–10<sup>7</sup>）。"),
    ("The total computational cost of the dataset is 310, 835 CPU-hours for 2, 448 snapshots.", "整个数据集的计算成本为 310,835 CPU 小时，共 2,448 个快照。"),
    ("The corresponding R-squared values are 0.9772 and 0.9652.", "对应的 R<sup>2</sup> 分别为 0.9772 和 0.9652。"),
    ("SW2 (Λ𝑜𝑢𝑡), the outboard leading-edge sweep angle.", "SW2（Λ<sub>out</sub>）为外翼前缘后掠角。"),
    ("The data were collected during the 20th century.", "这些数据采集于 20 世纪。"),
    ("Finetuning can achieve 2-3x lower errors and use 8x fewer samples.", "微调可使误差低 2-3 倍，所需样本少 8 倍。"),
    ("Except those of F- FNO and Galerkin, the results are cited.", "除 F-FNO 和 Galerkin 外，结果均为引用。"),
    ("These meshes can exceed 100 million cells.", "这些网格可超过 1 亿个单元。"),
    ("We train models with 0.1 to 2.4 million parameters.", "训练参数量为 0.1 至 2.4 百万的模型。"),
    ("The differences are ∆eRel-L2 = −0.0189 and ∆eTKE = +0.1196.", "差值为 ∆e<sub>Rel-L2</sub> = −0.0189 和 ∆e<sub>TKE</sub> = +0.1196。"),
    ("We apply the kernels to all queries.", "对所有 query 使用 kernel。"),
    ("The Fourier neural operator is used as the baseline.", "以 FNO 作为基线。"),
    ("During pretraining, we leverage a heterogeneous collection of PDE datasets drawn from PDEBench (Takamoto et al., 2022), "
     "PDENNEval (Wei et al., 2024), and The Well (Ohana et al., 2024).",
     "预训练阶段，我们使用来自 PDEBench（Takamoto et al., 2022）、PDENNEval（Wei et al., 2024）和 The Well（Ohana et al., 2024）的一组异构 PDE 数据集。"),
    ("Thus, Transolver does not need a Transformer at all.", "因此，Transolver 根本不需要 Transformer。"),
    ("Transolver is used with width 256, eight attention heads, an MLP ratio of 2, and 32 physics-aware slice tokens.",
     "Transolver 的宽度为 256、8 个 attention heads、MLP 比率为 2，以及 32 个 physics-aware slice tokens。"),
    ("The L32/L8 error ratio remains below one for pretrained models but above one for scratch.",
     "预训练模型的 L32/L8 误差比小于 1，而 Scratch 的这一比值大于 1。"),
    ("The corpora correspond to approximately 1.41, 5.16, and 11.60 thousand A100-hours of simulation.",
     "这些语料的模拟成本以千 A100-hours 计，分别约为 1.41、5.16 和 11.60。"),
    ("Finetuning reaches a target error with 8–16× fewer training samples.", "微调只需原来 1/8–1/16 的训练样本就能达到目标误差。"),
    ("Both settings follow the same pretrain-and-finetune procedure(Figure.2).", "两种设置遵循相同的预训练与微调流程（图 2）。"),
    ("The resulting non-dimensional fields have approximately unit scale.", "得到的无量纲场尺度约为 1。"),
    ("Accuracy improves by 2.1% and 3 points on the two benchmarks.", "在两个基准上准确率提升 2.1%，3 个点。"),
])
def test_accepts_faithful_translations_of_extracted_text(source, translated):
    assert translation_warnings(source, translated) == []


@pytest.mark.parametrize(("source", "translated"), [
    ("Our model is trained with an initial learning rate of 1 × 10−3.", "模型的初始学习率为 1 × 10<sup>−4</sup>。"),
    ("We train on a resolution of 852.", "用 86² 的数据训练。"),
    ("These meshes can exceed 100 million cells.", "这些网格可超过 1 千万个单元。"),
    ("We train the model on the data.", "我们用 ResNet 在数据上训练模型。"),
    ("The model works well on the data.", "FNO 模型在数据上效果好。"),
    ("The model uses eight attention heads.", "模型使用 9 个 attention heads。"),
    ("The model is trained on 8 samples.", "模型只用 1/8 的样本训练。"),
])
def test_still_flags_numbers_and_terms_the_text_lacks(source, translated):
    warnings = translation_warnings(source, translated)
    assert warnings and any("not present" in r for r in warnings[0]["reasons"]), (source, translated)


def test_a_translation_that_leaves_out_most_of_the_sentence_is_short():
    warnings = translation_warnings("The model reduces the error on all six benchmarks while using fewer parameters and less training time.",
                                    "模型降低了误差。")
    assert warnings and "short" in warnings[0]["reasons"][-1]


def test_percent_written_out_matches_the_sign():
    assert translation_warnings("Accuracy improves by 15 percent on the benchmark.", "在基准上准确率提高 15%。") == []
    assert translation_warnings("Accuracy improves by 15 per cent on the benchmark.", "在基准上准确率提高 15%。") == []


def test_a_warning_quotes_the_number_as_the_comment_writes_it():
    warnings = translation_warnings("The model has 175B parameters in total.", "该模型共有 1750 亿个参数，训练了 100 轮。")
    reason = warnings[0]["reasons"][0]
    assert "1750 亿" in reason and "100" in reason and "E+" not in reason
