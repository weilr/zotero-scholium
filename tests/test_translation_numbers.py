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
    ("Models with up to 6B parameters.", "最多 6 亿参数的模型。"),
    ("The dataset has 1.5M examples.", "数据集有 15 万个样例。"),
    ("Llama-7B is small.", "Llama-70B 很小。"),
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
    # a magnitude as a capital suffix or a word, and the same value with 万 or 亿
    ("Models with up to 6B parameters.", "最多 60 亿参数的模型。"),
    ("The dataset has 1.5M examples.", "数据集有 150 万个样例。"),
    ("We train for 10K steps.", "训练 1 万步。"),
    ("Models with 6 billion parameters.", "参数为 60 亿的模型。"),
    ("GPT-3 has 175B parameters.", "GPT-3 有 1750 亿参数。"),
    ("A 7B model.", "一个 7B 模型。"),
    ("Llama-7B is small.", "Llama-7B 很小。"),
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
    ("Since the magnitudes of the gradients produced by the soft targets scale as 1/T 2 it is important to multiply them by T 2.",
     "由于软目标产生的梯度幅值按 1/T² 缩放，需要把它们乘以 T²。"),
    ("We trained on 2 trillion tokens of data.", "我们用 2 万亿个 token 的数据训练。"),
    ("Despite this, the distilled model only makes 206 test errors of which 133 are on the 1010 threes in the test set.",
     "尽管如此，蒸馏模型只产生 206 个测试错误，其中 133 个出现在测试集的 1010 个 3 上。"),
    ("If this bias is increased by 3.5, the distilled model makes 109 errors of which 14 are on 3s.",
     "如果把该偏置增加 3.5，蒸馏模型的错误降为 109 个，其中 3 的错误为 14 个。"),
    ("We use an architecture with 8 hidden layers each containing 2560 rectiﬁed linear units.",
     "我们使用的结构有 8 个隐藏层，每层 2560 个 ReLU 单元。"),
    ("Our 152- layer residual net is the deepest network ever presented on ImageNet.",
     "我们的 152 层残差网络是迄今在 ImageNet 上提出的最深网络。"),
    ("Our 34- layer baseline has 3.6 billion FLOPs (multiply-adds).", "我们的 34 层基线有 36 亿次浮点运算（乘加）。"),
    ("On 256x256 LSUN, we obtain sample quality similar to ProgressiveGAN.", "在 256×256 的 LSUN 上，样本质量与 ProgressiveGAN 相近。"),
    ("The convolutional layers mostly have 3x3 filters.", "卷积层大多使用 3×3 的滤波器。"),
    ("GPT-4 generally lacks knowledge of events that have occurred after the vast majority of its pre-training data cuts off "
     "in September 202110, and does not learn from its experience.",
     "GPT-4 通常缺乏对其预训练数据大部分截止的 2021 年 9 月之后发生的事件的知识，也不会从经验中学习。"),
    ("The data was collected in Feb. 2023.", "数据收集于 2023 年 2 月。"),
    ("The data was collected in Feb. 2023.", "データは2023年2月に収集された。"),
    ("The data was collected in Feb. 2023.", "데이터는 2023년 2월에 수집되었다."),
    ("The data was collected in September 2021.", "Les données ont été collectées en 09/2021."),
    # magnitudes as Japanese and Traditional Chinese write them
    ("These models have about 700 million parameters.", "これらのモデルのパラメータは約7億個である。"),
    ("These meshes can exceed 100 million cells.", "這些網格可超過 1 億個單元。"),
    ("We trained on 2 trillion tokens of data.", "我們用 2 萬億個 token 的資料訓練。"),
    ("The corpus holds 30 thousand documents.", "語料庫有 3 萬份文件。"),
    ("We use about 20M examples.", "약 2천만 개의 예제를 사용한다."),
    ("The corpus holds 30 thousand documents.", "말뭉치에는 3만 개의 문서가 있다."),
    ("A smaller net with two hidden layers of 800 rectified linear hidden units.",
     "각 층에 800개의 ReLU 은닉 유닛이 있는 은닉층 2개짜리 작은 네트워크."),
    ("The final softmax layer has 14,000 labels and the training set has 23,000 hours of speech.",
     "La couche softmax finale compte 14 000 étiquettes et le jeu d'entraînement 23 000 heures de parole."),
    # what the extraction joins (152layer, CrowSPairs, API3), a name and its version, an abbreviation, a fraction
    ("Our 152layer residual net is the deepest network ever presented on ImageNet.", "我们的 152 层残差网络是迄今在 ImageNet 上提出的最深网络。"),
    ("InstructGPT does not significantly improve over GPT-3 on the Winogender (Rudinger et al., 2018) and CrowSPairs "
     "(Nangia et al., 2020) datasets.", "InstructGPT 在 Winogender 和 CrowS-Pairs 数据集上相对 GPT-3 没有明显改善。"),
    ("InstructGPT does not significantly improve over GPT-3 on the Winogender (Rudinger et al., 2018) and CrowSPairs "
     "(Nangia et al., 2020) datasets.", "InstructGPT在Winogender和CrowS-Pairs数据集上相对GPT-3没有明显改善。"),
    ("The error stays below one in ten million samples.", "误差低于 1 千万分之一。"),
    ("Only layer 3 is fine-tuned in all experiments.", "모든 실험에서 레이어 3만 미세 조정한다."),
    # a digit's German noun
    ("So the distilled model gets 98.6% of the test 3s correct despite never having seen a 3 during training.",
     "Daher erkennt das destillierte Modell 98,6 % der Test-3er richtig, obwohl es im Training nie eine 3 gesehen hat."),
    # two numbers sharing their magnitude
    ("Its complexity is lower than VGG-16/19 nets (15.3/19.6 billion FLOPs).", "其复杂度低于 VGG-16/19（153/196 亿 FLOPs）。"),
    ("Its complexity is lower than VGG-16/19 nets (15.3/19.6 billion FLOPs).", "其复杂度低于 VGG-16/19（153 亿/196 亿 FLOPs）。"),
    # a number in parts of falling magnitude is their sum
    ("The model has 350 million parameters.", "모델의 파라미터는 3억 5천만 개다."),
    ("The model has 350 million parameters.", "このモデルのパラメータは3億5000万個である。"),
    ("The corpus holds 12,000 documents.", "语料库有 1万2千 份文档。"),
    ("We collect prompts submitted to the OpenAI API3 and some labeler-written prompts.", "我们收集提交到 OpenAI API 的提示以及部分标注者撰写的提示。"),
    ("We find that GPT-4 outperforms the English-language performance of GPT 3.5 and existing language models.",
     "我们发现 GPT-4 超过了 GPT-3.5 的英语表现以及现有语言模型。"),
    ("The gap between train and test is at most 0.03 bits per dimension.", "训练集与测试集之间的差距至多为 0.03 bits/dim。"),
    ("This allowed us to predict GPT-4's performance based on models trained with no more than 1/1,000th the compute of GPT-4.",
     "这使我们能够基于计算量不超过 GPT-4 千分之一的模型，预测 GPT-4 的性能。"),
    ("We initialize πref by maximizing likelihood, that is, πref = arg maxπ Ex,yw∼D [log π(yw | x)].",
     "通过最大化似然来初始化 πref，即 πref = argmax<sub>π</sub> E[log π(yw | x)]。"),
    ("The model recovers almost all the information in the full training set (about 2% shy).",
     "该模型几乎恢复了完整训练集中的全部信息，仅差约 2 个百分点。"),
    ("Accuracy rises by 3 percentage points on the benchmark.", "在基准上准确率提高 3 个百分点。"),
    # articles and prepositions need no characters of their own
    ("Llama 2-Chat 70B model has a win rate of 36% and a tie rate of 31.5% relative to ChatGPT.",
     "Llama 2-Chat 70B 相对 ChatGPT 的胜率为 36%，平局率为 31.5%。"),
])
def test_accepts_faithful_translations_of_extracted_text(source, translated):
    assert translation_warnings(source, translated) == []


@pytest.mark.parametrize(("source", "translated"), [
    ("Our model is trained with an initial learning rate of 1 × 10−3.", "模型的初始学习率为 1 × 10<sup>−4</sup>。"),
    ("We train on a resolution of 852.", "用 86² 的数据训练。"),
    ("These meshes can exceed 100 million cells.", "这些网格可超过 1 千万个单元。"),
    ("We train the model on the data.", "我们用 ResNet 在数据上训练模型。"),
    ("It usually includes three phases: supervised fine-tuning, reward learning and RL optimization.",
     "RLHF 通常包括三个阶段：监督微调、奖励学习和强化学习优化。"),
    ("We use 8 hidden layers.", "我们使用 8 个 ReLU 隐藏层。"),
    ("The model was trained on 200000 samples.", "模型用 2000 个样本训练。"),
    ("The model was released in 2023.", "模型于 2023 年 9 月发布。"),
    # names with two capitals are no abbreviation of two words; a seconds count, "the ones", a name like May, the number of
    # a footnote are no numbers a translation may add
    ("We train the model on a large dataset in natural images.", "我们在 ImageNet 的自然图像大数据集上训练模型。"),
    ("The loss is computed per token weighting.", "损失用 PyTorch 按 token 加权计算。"),
    ("Each step takes 5s on one GPU.", "每步在一块 GPU 上需要 5 分钟。"),
    ("We keep the ones that pass the filter.", "我们保留通过过滤的 1 个样本。"),
    ("May Chen collected the data.", "May Chen 收集了 5 份数据。"),
    ("Data cuts off in September 202110, before the launch.", "数据截止于 2021 年 10 月，早于发布。"),
    ("These models have about 700 million parameters.", "これらのモデルのパラメータは約70億個である。"),
    ("We use about 20M examples.", "약 2만 개의 예제를 사용한다."),
    ("The final layer has 1,400 labels in this setting.", "La couche finale compte 14 000 étiquettes dans ce cadre."),
    ("We use the model on the data.", "우리는 ReLU 모델을 데이터에 사용한다."),
    ("The model works well on the data.", "FNO 模型在数据上效果好。"),
    ("The model uses eight attention heads.", "模型使用 9 个 attention heads。"),
    ("The model is trained on 8 samples.", "模型只用 1/8 的样本训练。"),
    ("Our 152layer residual net is the deepest network.", "我们的 50 层残差网络是最深的网络。"),
    ("We compare it with GPT 3.5 on the benchmark.", "我们在基准上把它与 GPT-4 比较。"),
    ("We train the model on the data.", "我们用 dim 在数据上训练模型。"),
    ("We study importance sampling for the model.", "我们研究 SAM 模型的重要性采样。"),
    ("The models were released in May 2021.", "2021 年 5 月，我们发布了 5 个模型。"),
    ("Its complexity is lower than VGG-16/19 nets (15.3/19.6 billion FLOPs).", "其复杂度低于 VGG-16/19（163/196 亿 FLOPs）。"),
    ("The model gets 98.6% of the test 3s correct.", "Das Modell erkennt 98,6 % der Test-5er richtig."),
    ("The model has 350 million parameters.", "모델의 파라미터는 3억 6천만 개다."),
])
def test_still_flags_numbers_and_terms_the_text_lacks(source, translated):
    warnings = translation_warnings(source, translated)
    assert warnings and any("not present" in r for r in warnings[0]["reasons"]), (source, translated)


def test_japanese_has_room_for_its_kana_but_a_much_longer_comment_is_still_long():
    assert translation_warnings("These models have about 700 million parameters.", "これらのモデルのパラメータは約7億個である。") == []
    w = translation_warnings("We use six layers in the model.",
                             "このモデルでは6つの層を使っているが、これは前の章で説明した設計とは大きく異なり、学習もかなり難しくなる。")
    assert w and any("long for the span" in r for r in w[0]["reasons"])


def test_a_magnitude_before_a_fraction_is_read_both_ways():
    """千分之一 is a thousandth: the 4 of GPT-4 before it is 4, while 5万分之一 is one in 50,000; 천분의 일 likewise."""
    for source, translated in [
            ("Models trained with no more than 1/1,000th the compute of GPT-4.", "计算量不超过 GPT-4 千分之一的模型。"),
            ("Models trained with no more than 1/1,000th the compute of GPT-4.", "GPT-4 천분의 일 이하의 계산으로 훈련한 모델."),
            ("The error stays below one in ten million.", "误差低于 1 千万分之一。"),
            ("The error is about one in 50,000.", "误差约为 5万分之一。")]:
        assert translation_warnings(source, translated) == [], translated
    assert translation_warnings("Models use 3 layers.", "模型使用 4 千分之一的层。")   # a 4 the text does not have
    assert cli._tokens("4 千个样本") == cli._tokens("4000") and cli._tokens("4万个样本") == cli._tokens("40000")


def test_korean_man_and_jo_after_a_number_are_also_words():
    for source, translated in [("Only layer 3 is fine-tuned.", "레이어 3 만 미세 조정한다."),
                               ("The image is cut into 3 pieces.", "이미지를 3조각으로 자른다."),
                               ("We test 3 conditions in total.", "총 3 조건을 시험한다.")]:
        assert translation_warnings(source, translated) == [], translated


def test_a_translation_that_leaves_out_most_of_the_sentence_is_short():
    warnings = translation_warnings("The model reduces the error on all six benchmarks while using fewer parameters and less training time.",
                                    "模型降低了误差。")
    assert warnings and "short" in warnings[0]["reasons"][-1]


def test_percent_written_out_matches_the_sign():
    assert translation_warnings("Accuracy improves by 15 percent on the benchmark.", "在基准上准确率提高 15%。") == []
    assert translation_warnings("Accuracy improves by 15 per cent on the benchmark.", "在基准上准确率提高 15%。") == []


def test_a_warning_quotes_the_number_as_the_comment_writes_it():
    warnings = translation_warnings("The model has many parameters in total.", "该模型共有 1750 亿个参数，训练了 100 轮。")
    reason = warnings[0]["reasons"][0]
    assert "1750 亿" in reason and "100" in reason and "E+" not in reason
    # a number grouped with a plain space, as French writes it by hand, is quoted with that space
    reason = translation_warnings("The final layer has 1,400 labels in this setting.",
                                  "La couche finale compte 14 000 étiquettes dans ce cadre.")[0]["reasons"][0]
    assert "14 000" in reason and "\xa0" not in reason


def test_a_warning_quotes_a_number_with_a_magnitude_suffix_as_the_comment_writes_it():
    reason = translation_warnings("We fine-tune LLaMA-2 7B.", "我们微调 LLaMA-2 13B。")[0]["reasons"][0]
    assert "13B" in reason and "billion" not in reason
    reason = translation_warnings("The model has 175B parameters in total.", "该模型共有 1750 亿个参数，训练了 100 轮。")[0]["reasons"][0]
    assert "100" in reason and "1750" not in reason, "175B and 1750 亿 are one number"


@pytest.mark.parametrize(("source", "translated"), [
    ("We fine-tune Llama-7B.", "我们微调 Llama 7B。"),
    ("We fine-tune Llama 7B.", "我们微调 Llama-7B。"),
    ("We compare Qwen2.5-7B and Mistral 7B.", "我们比较 Qwen2.5 7B 和 Mistral-7B。"),
])
def test_a_name_and_its_size_with_a_hyphen_or_a_space_are_one_name(source, translated):
    assert translation_warnings(source, translated) == []


def test_another_size_of_the_name_still_warns():
    assert translation_warnings("We fine-tune Llama-7B.", "我们微调 Llama 13B。")
    assert translation_warnings("We fine-tune Llama 7B.", "我们微调 Llama-13B。")
