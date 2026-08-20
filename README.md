# AI Video Remix

一个 [Claude Code](https://claude.com/claude-code) skill:把 (a) 一个想要二创/逆向还原的现有视频,或 (b) 一份想要原创改写的素材/需求,端到端做成一条装配好的竖屏(9:16)AI 视频——文案+SRT提取、分镜提示词设计、首帧图生成、多场景 ComfyUI MiniMax-H3 集群视频生成、精确时间线装配,最终在 PalmierPro 里完成。

在 Claude Code 里说"remix这个视频"、"把这段文案做成视频"、"照我们XX那套流程做个视频"之类的话,这个 skill 会自动触发。

## 安装(开箱即用)

把整个仓库克隆到你项目的 `.claude/skills/ai-video-remix/`:

```bash
git clone https://github.com/lumos-tiamo/ai-video-remix.git .claude/skills/ai-video-remix
```

Claude Code 会自动发现这个目录下的 `SKILL.md` 并注册这个 skill,不需要额外配置。

## 前置依赖

- **Claude Code**,已连接一个支持 MCP 的视频剪辑工具(这套流程默认用 `palmier-pro`)
- **Python 3** + `pip install edge-tts`(默认免费 TTS 后端)
- **FFmpeg**(拼接、抽帧、转码都要用到)
- 一个可访问的 **共享 ComfyUI 集群**,部署了 [ComfyUI-Distributed](https://github.com/robertvoy/ComfyUI-Distributed) 插件 + MiniMax H3 视频模型(master + 若干 worker 端口)
- 一个兼容 OpenAI 接口的网关 key(文案/生图用,项目里默认接的是 `newapi.elevatesphere.com`,换成你自己的网关也可以,脚本不写死具体服务商)
- 可选,仅阶段6用到:Node ≥22、Chrome(`npx hyperframes doctor` 检查)

## 配置

复制 `.env.example` 为 `.env`,填你自己的值:

```bash
cp .env.example .env
```

```
NEWAPI_KEY=sk-...                  # 你自己的网关 key,团队共用账号找管理员要一份自己的
NEWAPI_URL=https://newapi.elevatesphere.com
COMFYUI_HOST=192.168.100.215       # 你的 ComfyUI 集群地址
COMFYUI_MASTER_PORT=8188
COMFYUI_WORKER_PORTS=8189,8190,8191,8192,8193,8194,8195
```

所有脚本都从环境变量读配置(见 `scripts/config.py`,从当前目录向上找 `.env`),没有硬编码的 key/host/端口。**`.env` 已经在 `.gitignore` 里,不要提交,也不要把 key 直接贴进对话里。**

## 用法

不需要手动跑脚本——直接在 Claude Code 里用自然语言描述需求(比如"把这条视频重新做成海绵宝宝科普风格,60秒左右"),Claude 会按 `SKILL.md` 里的流程自己调度这些脚本、在关键检查点(文案确认、首帧图确认)停下来给你看产出物,其余阶段全自动跑完。

## 流程总览

| 阶段 | 做什么 | 脚本 |
|---|---|---|
| 1. 文案+SRT | 逆向还原源视频文案,或原创写稿;按*实测*TTS时长定每个场景的目标秒数 | `write_scenes.py`, `gen_tts.py`, `gen_srt.py` |
| 2. 首帧图 | 每个场景一张参考图 | `gen_images.py` |
| 3. 场景视频生成 | ComfyUI 集群上跑 MiniMax H3,支持顺序/并行两种真实可用模式 | `gen_scene_master_only.py`, `gen_scenes_parallel.py` |
| 4. PalmierPro 装配 | 摆放视频+音频+字幕到时间线,精确对齐 | `compute_placement.py` |
| 5. 导出 | 导出最终 mp4 | (palmier-pro MCP 工具) |
| 6. (可选)HyperFrames 卡拉OK字幕 | 逐字高亮的硬烧录字幕,后处理叠加层 | `build_karaoke_transcript.py`, `gen_karaoke_composition.py`, `gen_word_timestamps_fallback.py` |

**场景视频生成三种模式怎么选**(阶段3是这条流水线里最容易踩坑的地方,细节和判断依据都在 `SKILL.md` 阶段3):

1. 顺序、只走 master(默认,最稳)
2. 裸端口并行(`gen_scenes_parallel.py`,场景多、赶时间时用,已知有个别 worker 偶尔卡住的风险)
3. 官方 `/distributed/queue` + `DistributedCollector` 协议(`distributed_submit.py`)——只适合"同一场景多个seed候选版本"这种需求,不是给多场景提速用的

## 详细文档

所有实测踩过的坑、参数取值依据、模型清单都在 [`SKILL.md`](./SKILL.md) 里——尤其是阶段3(GPU 集群)和阶段6(HyperFrames)开头都写了"动手之前把这一整节看完",不是虚话,跳过直接踩坑的成本远高于读一遍的成本。

## 目录结构

```
SKILL.md                          # 完整流程文档,Claude Code 的行为契约
.env.example                      # 环境变量模板
scripts/
  config.py                       # 从 .env 读配置,所有脚本共用
  write_scenes.py                 # 阶段1:文案→场景列表
  gen_tts.py                      # TTS(edge-tts 默认 / newapi 可选),字级时间戳
  gen_srt.py                      # 生成字幕SRT
  gen_images.py                   # 阶段2:首帧图生成
  comfy_client.py                 # ComfyUI 请求/轮询/抽帧/拼接的共享工具
  gen_scene_master_only.py        # 阶段3模式1:顺序,只走 master
  gen_scenes_parallel.py          # 阶段3模式2:裸端口真并行
  distributed_submit.py           # 阶段3模式3:官方 Collector 协议示例(同场景多候选场景用)
  compute_placement.py            # 阶段4:时间线摆放数学
  gen_word_timestamps_fallback.py # 阶段6:本地 Whisper 补字级时间戳
  build_karaoke_transcript.py     # 阶段6:字级时间戳→分组字幕
  gen_karaoke_composition.py      # 阶段6:生成 HyperFrames 项目
```
