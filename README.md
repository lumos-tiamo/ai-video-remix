# AI Video Remix

一个跨 [Claude Code](https://claude.com/claude-code) / Codex CLI 的 agent skill:把 (a) 一个想要二创/逆向还原的现有视频,或 (b) 一份想要原创改写的素材/需求,端到端做成一条装配好的竖屏(9:16)或横屏(16:9)AI 视频——文案+SRT提取、分镜提示词设计、首帧图生成、多场景 ComfyUI MiniMax-H3 集群视频生成、精确时间线装配,最终在 PalmierPro 里完成。

**风格无关**:同一套骨架已经在多种不同风格的真实生产上跑通过——时事财经历史锐评(厚涂油画单主体)、AI女团MV(真实歌曲驱动口型同步)、IP吉祥物二创(角色自动核验)、纪录片式建造改造(全片一镜到底)、插画/YA剧情连载、恋爱人设短剧、宠物喜剧二创。拿到一个新风格的需求,先看 `SKILL.md` 开头的"风格速查表"对号入座,再看 `references/style_playbooks.md` 里对应那一节的具体做法——不需要从零摸索。

在 Claude Code 或 Codex CLI 里说"remix这个视频"、"把这段文案做成视频"、"照我们XX那套流程做个视频"之类的话,这个 skill 会自动触发。

> **只是日常提需求、不负责搭环境?** 看 [`使用指南.md`](./使用指南.md) 就够了,不用往下读这份技术安装文档。

---

## 目录

- [安装](#安装开箱即用)
- [Codex CLI 兼容](#codex-cli-兼容)
- [前置依赖](#前置依赖)
- [配置](#配置)
- [用法](#用法)
- [流程总览](#流程总览)
- [详细文档](#详细文档)
- [目录结构](#目录结构)

---

## 安装(开箱即用)

把整个仓库克隆到你项目的 `.claude/skills/ai-video-remix/`:

```bash
git clone https://github.com/lumos-tiamo/ai-video-remix.git .claude/skills/ai-video-remix
```

Claude Code 会自动发现这个目录下的 `SKILL.md` 并注册这个 skill,不需要额外配置。

---

## Codex CLI 兼容

这个 skill 同时在 **Claude Code** 和 **Codex CLI** 下有效,不需要维护两份内容——两边认的是同一份 `SKILL.md` 格式(开放 agent skills 标准),只是项目级 skill 的扫描目录不一样:

| | Claude Code | Codex CLI |
|---|---|---|
| 扫描目录 | `.claude/skills/` | `.agents/skills/`(从当前目录向上扫到仓库根) |
| 显式调用 | `/skill-name` | `/skills` 或 `$skill-name` |
| 自然语言自动触发 | 支持 | 支持,机制相同 |

同事只用 Claude Code:上面"安装"那步做完就够了,不用管这一节。

**同事用 Codex CLI**:Codex 官方支持 symlink 并会跟随其指向的目标,所以不用再克隆一份、也不用维护两份内容,建一个软链接指过去就行(在你项目根目录执行):

```bash
mkdir -p .agents/skills
ln -s ../../.claude/skills/ai-video-remix .agents/skills/ai-video-remix
```

两个目录读的是完全同一份文件,改一处两边同时生效。除此之外,Codex 用户还要单独做一件事——**给 Palmier-Pro 的 MCP 连接**:这是每个人自己电脑上 `~/.codex/config.toml`(或项目级 `.codex/config.toml`)里的配置,跟 Claude Code 的 MCP 设置是两套独立的东西,不会因为克隆/软链接这个仓库而自动带过去,具体注册命令找负责 Palmier-Pro 接入的同事要(取决于服务端暴露的是 stdio 还是 HTTP,`codex mcp add` 的参数不一样)。除了这两件事,`.env`/ComfyUI集群/网关key 这些环境配置对两边客户端完全通用,不用重复配置。

---

## 前置依赖

**软件/工具(自己装):**

- **git**(克隆这个仓库,仅安装时用一次)
- **Claude Code 或 Codex CLI**,已连接一个支持 MCP 的视频剪辑工具(这套流程默认用 `palmier-pro`——这是独立于本仓库的另一套 MCP 连接配置,Claude Code 和 Codex 两边要分别配一次,不在这份文档范围内,找负责的同事要接入方式)
- **Python 3** + `pip install edge-tts`(默认免费 TTS 后端)+ `pip install Pillow`(生成发布封面图 `make_cover.py` 用)
- **FFmpeg + ffprobe**(拼接、抽帧、转码、字幕切变检测都要用到)
- 可选,仅阶段6(HyperFrames)或 newapi 配音时补字级时间戳用到:**Node ≥22**、**Chrome**(`npx hyperframes doctor` 检查)

**共享基础设施(找管理员要访问权限,不是自己装):**

- 一个可访问的 **共享 ComfyUI 集群**,部署了 [ComfyUI-Distributed](https://github.com/robertvoy/ComfyUI-Distributed) 插件 + MiniMax H3 视频模型(master + 若干 worker 端口)
- 一个兼容 OpenAI 接口的网关 key(文案/生图用,项目里默认接的是 `newapi.elevatesphere.com`,换成你自己的网关也可以,脚本不写死具体服务商)——团队共用账号找管理员要一份自己的,不要共用同一个 key

---

## 配置

复制 `.env.example` 为 `.env`,填你自己的值:

```bash
cp .env.example .env
```

**必需变量**(缺一个都跑不起来):

```
NEWAPI_KEY=sk-...                  # 你自己的网关 key,团队共用账号找管理员要一份自己的
NEWAPI_URL=https://newapi.elevatesphere.com
COMFYUI_HOST=192.168.100.215       # 你的 ComfyUI 集群地址
COMFYUI_MASTER_PORT=8188
COMFYUI_WORKER_PORTS=8189,8190,8191,8192,8193,8194,8195
```

**可选变量**(有默认值,或只有用到对应功能才需要,完整清单+说明见 `.env.example`):

| 变量 | 作用 | 不填会怎样 |
|---|---|---|
| `IMAGE_API_KEY` / `IMAGE_API_URL` | 给阶段2首帧图单独指定一个网关 | fallback 到 `NEWAPI_*` |
| `COMFYUI_MAX_CONCURRENT` | 集群并发上限 | 默认 `3`(保守值,GPU可能被多个端口共享) |
| `FISHAUDIO_KEY` | 克隆音色 TTS(`gen_tts_fishaudio.py`) | 不用这个后端就不需要 |
| `ELEVENLABS_KEY` | 更自然的付费 TTS(`gen_tts_elevenlabs.py`) | 不用这个后端就不需要 |
| `VERIFIER_MODEL` | 角色一致性核验用的判图模型 | 默认 `gemini-2.5-pro` |
| `MAX_GEN_ATTEMPTS` | 角色核验最多重试几次 | 默认 `3` |
| `VERIFY_MODE` | 角色核验模式,额度紧张时可设 `off` 应急关闭 | 默认 `critical-only` |

所有脚本都从环境变量读配置(见 `scripts/config.py`,从当前目录向上找 `.env`),没有硬编码的 key/host/端口。**`.env` 已经在 `.gitignore` 里,不要提交,也不要把 key 直接贴进对话里。**

**排查并发数异常/配置好像没生效时,先查 `.env` 是不是被就近覆盖了**——`config.py` 从当前工作目录向上找 `.env`,如果你在某个具体项目目录下也放了一份 `.env`,它会盖掉 skill 目录这份,曾经因此把8端口集群意外限流到3并发。

---

## 用法

不需要手动跑脚本——直接在 Claude Code 或 Codex CLI 里用自然语言描述需求(比如"把这条视频重新做成海绵宝宝科普风格,60秒左右"),它会按 `SKILL.md` 里的流程自己调度这些脚本、在关键检查点(文案确认、首帧图确认)停下来给你看产出物,其余阶段全自动跑完。

---

## 流程总览

| 阶段 | 做什么 | 脚本 |
|---|---|---|
| 1. 文案+SRT | 逆向还原源视频文案,或原创写稿;按*实测*TTS时长定每个场景的目标秒数 | `write_scenes.py`, `gen_tts.py`, `gen_srt.py` |
| 2. 首帧图 | 每个场景一张参考图 | `gen_images.py` |
| 3. 场景视频生成 | ComfyUI 集群上跑 MiniMax H3,四种真实可用调度模式(见下)+ 可选跨场景一镜到底衔接 | `gen_scene_master_only.py`, `gen_scenes_parallel.py` |
| 4. PalmierPro 装配 + 配乐 | 摆放视频+音频+字幕到时间线,精确对齐;按风格决定BGM怎么来(复用源音轨/歌曲驱动生成/外部曲库混音三选一) | `compute_placement.py` |
| 5. 导出 | 导出最终 mp4 | (palmier-pro MCP 工具) |
| 6. (可选)HyperFrames 卡拉OK字幕 | 逐字高亮的硬烧录字幕,后处理叠加层 | `build_karaoke_transcript.py`, `gen_karaoke_composition.py`, `gen_word_timestamps_fallback.py` |

**风格适配**:阶段1-5的骨架对任何风格通用,真正因风格而变的是画幅/画风/角色一致性机制/BGM策略/要不要做跨场景首尾帧衔接——`SKILL.md` 开头的风格速查表 + `references/style_playbooks.md` 覆盖了已验证风格(时事锐评、AI女团MV、IP吉祥物二创、AI建筑、AI漫剧、AI女友、宠物喜剧二创)的具体取值,新风格产出后按同样格式追加。

**场景视频生成四种调度模式怎么选**(阶段3是这条流水线里最容易踩坑的地方,细节和判断依据都在 `SKILL.md` 阶段3):

1. 顺序、只走 master(默认,最稳)
2. 裸端口并行(`gen_scenes_parallel.py`,同一条视频场景多、赶时间时用,已知有个别 worker 偶尔卡住的风险)
3. 官方 `/distributed/queue` + `DistributedCollector` 协议(`distributed_submit.py`)——只适合"同一场景多个seed候选版本"这种需求,不是给多场景提速用的
4. 多个独立项目各自绑定固定端口子集并发跑——同时赶好几条不相关视频时用,项目之间物理隔离互不排队

需要"生成画面按真实歌曲精确对口型"(音乐视频类需求)时,还有 `MiniMaxH3ReferenceToVideo` 这条替代节点路径(多参考图+参考音频,取代默认的 `MiniMaxH3ImageToVideo`),具体见 `references/style_playbooks.md` 的 AI女团MV 一节。

---

## 详细文档

所有实测踩过的坑、参数取值依据、模型清单都在 [`SKILL.md`](./SKILL.md) 里——尤其是阶段3(GPU 集群,含8端口调度模式、跨场景一镜到底衔接、延时摄影的真实结论)和阶段6(HyperFrames)开头都写了"动手之前把这一整节看完",不是虚话,跳过直接踩坑的成本远高于读一遍的成本。各已验证风格的具体做法(角色一致性机制选哪种、BGM从哪来、要不要做首尾帧衔接)在 [`references/style_playbooks.md`](./references/style_playbooks.md) 里按风格分节写清楚了。角色圣经(`character_bible.py`)完整 schema 见 [`references/character_bible.schema.md`](./references/character_bible.schema.md)。

---

## 目录结构

```
SKILL.md                          # 完整流程文档,Claude Code / Codex 的行为契约
README.md                         # 本文件:安装+快速上手
.env.example                      # 环境变量模板
references/
  style_playbooks.md              # 各已验证风格的具体做法(角色一致性/BGM/场景衔接/端口调度)
  character_bible.schema.md       # 固定IP角色一致性机制的完整 schema
scripts/
  config.py                       # 从 .env 读配置,所有脚本共用
  write_scenes.py                 # 阶段1:文案→场景列表(逆向还原/原创写稿共用)
  run_stage1.py                   # 阶段1:硬字幕源视频的完整链路封装(抽字幕→OCR→转写→分镜)
  extract_hardcoded_subs.py       # 阶段1:源视频硬字幕区域场景切变检测+批量OCR
  dialogueize_scenes.py           # 阶段1:把旁白式 narration 改写成真实对话台词
  translate_dialogue.py           # 阶段1:批量翻译场景对话为另一种语言
  gen_tts.py                      # TTS(edge-tts 默认 / newapi 可选),字级时间戳
  gen_tts_multivoice.py           # TTS:按角色分配不同音色(多角色对话剧用)
  gen_tts_fishaudio.py            # TTS:接入 Fish Audio 克隆音色
  gen_tts_elevenlabs.py           # TTS:接入 ElevenLabs(更自然但付费)
  gen_srt.py                      # 生成字幕SRT
  gen_bilingual_srt.py            # 生成双语字幕SRT(原文+译文双行)
  gen_images.py                   # 阶段2:首帧图生成(gpt-image-2 主力 + Z-Image Turbo 兜底)
  gen_images_parallel.py          # 阶段2并行版:只补生成还没有图的场景
  gen_images_ref.py               # 阶段2:接入 character_bible 的图生图版本,带自动核验
  gen_images_zimage.py            # 阶段2:本地 Z-Image Turbo 生成(gen_images.py 的兜底通道)
  character_bible.py              # 固定IP角色一致性:角色圣经数据结构与校验规则
  verify_character.py             # 固定IP角色一致性:生成后自动核验+有界重试
  lint_scenes_against_bible.py    # 批量检查/修复 scenes.json 对角色圣经约束的覆盖缺口
  color_metrics.py                # verify_character.py 用:感知色差(CIEDE2000)风格漂移代理
  correction_loop.py              # verify_character.py 用:有界重试的停止策略状态机
  image_hash.py                   # verify_character.py 用:感知哈希近重复检测
  per_feature.py                  # verify_character.py 用:逐特征核验(关键特征一票否决)
  make_cover.py                   # 生成发布用竖版封面图
  prepend_style_prefix.py         # 批量给 scenes.json 所有 image_prompt 前置统一风格锁定语
  restyle_scenes.py               # 把已有 scenes.json 重新改写成另一种画风(保留场景结构)
  comfy_client.py                 # ComfyUI 请求/轮询/抽帧/拼接的共享工具
  gen_scene_master_only.py        # 阶段3模式1:顺序,只走 master
  gen_scenes_parallel.py          # 阶段3模式2:裸端口真并行,pick_idle_port() 按实时队列深度分配
  distributed_submit.py           # 阶段3模式3:官方 Collector 协议示例(同场景多候选场景用)
  compute_placement.py            # 阶段4:时间线摆放数学
  gen_word_timestamps_fallback.py # 阶段6:本地 Whisper 补字级时间戳
  build_karaoke_transcript.py     # 阶段6:字级时间戳→分组字幕
  gen_karaoke_composition.py      # 阶段6:生成 HyperFrames 项目
```
