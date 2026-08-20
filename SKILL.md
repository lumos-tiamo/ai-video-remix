---
name: ai-video-remix
description: 把一个源视频(二创/逆向还原)或一份原始素材/需求(原创写稿),端到端做成一条在 PalmierPro 里装配好的竖屏 AI 视频。覆盖文案+SRT提取、分镜提示词设计、首帧图生成、多场景 ComfyUI MiniMax-H3 集群视频生成、精确时间线装配。当被要求"remix这个视频"、"把这段文案做成视频"、"照我们比奇堡/Doge那套流程做个视频"等端到端视频生成需求时使用。
---

# AI Video Remix

把 (a) 一个想要二创/逆向还原的现有视频,或 (b) 一份想要原创改写的素材/需求,做成一条完整的竖屏(9:16)视频:配音 + 字幕 + 每个分镜的 AI 生成视频片段,最终在 PalmierPro 里装配完成。

这套流程从两次实际产出中提炼而来:一条约5.5分钟的狗狗币科普视频(28个分镜,逆向还原文案),和一条约30秒的海绵宝宝/经济学科普视频(5个分镜,原创写稿,过程中还修正过一次角色识别错误)。下面每一条"坑"都是真的踩过才写的——跳过任何一步之前,先读一遍,尤其是 GPU 集群那一节。

## 检查点(不要跳过)

这是一条又长又贵的流水线。除非用户明确给了本次任务完全自主权,否则每个检查点都要停下来,把实际产出给用户看过再继续:

1. **阶段1完成后**(文案 + SRT + 分镜拆分)—— 确认故事/节奏对不对,**尤其是人名和专有名词**。这一步错了,后面所有 GPU 算力都会浪费在错误的内容上(实际发生过:视频的 ASR 转写文本把"章鱼哥"识别成了"张渔哥"、"珊迪"识别成了"山地",读音接近但是完全不同的角色,如果没有对照该内容系列的已知角色去核对,会直接把错误的名字用到底,分镜图、视频、字幕全部跟着错)。
2. **阶段2完成后**(首帧图)—— 确认人物/风格对不对,再烧 GPU 时间把一张画错的参考图动画化。**如果源内容涉及已知角色(比如海绵宝宝宇宙里的具体角色),要按角色库核实,不要自己发明一个通用角色顶替**——这正是上面那个人名错误连带出来的问题:提示词里写的是泛泛的"一条鱼""一头鲸鱼银行家",而不是真正的章鱼哥、珊迪,生成出来的图自然认不出是谁。
3. 就算用户明确说"你自主决定、不用等我确认",阶段1和阶段2这两个检查点也建议至少留一份产出物给用户回看——省下的不是审核这一步,而是省下"发现错了要不要现在改"这个决策权。
4. 其余阶段(视频生成、时间线装配、导出)在1、2都确认过之后可以完全无人值守跑完。

## 环境准备

把项目根目录的 `.env.example` 复制成 `.env`,填入你自己的值——绝不要把 `.env` 提交进 git,也不要把 key 硬编码进脚本里。这里所有脚本都从环境变量读配置(见 `scripts/config.py`),不是写死的字面量。

```
NEWAPI_KEY=sk-...           # 你自己的 newapi.elevatesphere.com key(或兼容的 OpenAI 风格网关)
NEWAPI_URL=https://newapi.elevatesphere.com
COMFYUI_HOST=192.168.100.215
COMFYUI_MASTER_PORT=8188
COMFYUI_WORKER_PORTS=8189,8190,8191,8192,8193,8194,8195
```

如果 key 是团队共用账号,找管理 newapi 的人要一份自己的——不要让同事直接把 key 贴进对话里,那样会留在聊天记录/日志里。

## 阶段1 —— 文案 + SRT(两种模式,同一份产出契约)

两种模式都用同一个脚本 `scripts/write_scenes.py`——区别只在于你传给它的"素材"是什么,不是两套代码。

**模式A——逆向还原现有视频**:抽帧+源视频的文案,喂给支持看图的模型(newapi 上 Gemini 3.x-pro 或 GPT-5.x 系列都支持多图输入),让它识别叙事节拍,按目标风格和目标时长重写成新文案。如果源视频旁边已经有现成的 `.txt` 转写文本(下载的社交媒体短视频通常会有),优先直接读那个,不要自己重新转写——更快也更准。**但转写文本里的人名/专有名词不能照单全收,尤其是同音字/近音字导致的 ASR 错误**,要对照该内容系列已知的角色/人名库核实一遍。

**模式B——凭素材原创写稿**(`scripts/write_scenes.py`):没有源视频,直接把用户的素材/需求 + 目标风格 + 目标时长交给一个强文本模型(claude-opus、gpt-5.x、gemini-3.x-pro 都可以)。如果用户想要特定的口播风格(比如"小Lin说"style的财经解说),先看看有没有现成的写作风格 skill(这个环境里有 `xiaolin-shuo-voiceover`),别自己从零摸索那个腔调。

两种模式最终都要收敛到同一份输出:一份场景列表,每个场景有 `narration`(这一拍要说的话)和足够驱动阶段2/3的画面描述。**不要提前猜帧数或秒数**——先把文案写出来,过一遍 TTS(`scripts/gen_tts.py`),用每个场景*实际测出来*的音频时长作为目标时长。猜一个"每字多少秒"然后跳过这一步,正是那种"提前精确、实际全错"的坑——去测量,不要去估算。

目标时长的数学关系:全部旁白文字的总长度大致要匹配目标视频时长 × 该 TTS 音色的真实语速(语速因音色和语言而异,测一小段就知道,别凭感觉猜——中文旁白在 `qwen3-tts-base`/`zora` 音色下实测约 3.3 字/秒,`edge-tts` 的 `zh-CN-YunjianNeural` 音色实测约 4.3-4.6 字/秒,都明显比"正常朗读语速"的直觉猜测慢/快,不能想当然)。

## 阶段2 —— 首帧图

每个场景一张参考图,由 `image_prompt` 生成(即使是中文旁白的视频,用英文写图片提示词也没问题——图片模型和视频模型都能理解,而且英文提示词在不同厂商之间的可预测性更好)。用真正的生图模型,不要用占位图:

```
POST {NEWAPI_URL}/v1/images/generations
{"model": "gpt-image-2", "prompt": "...", "n": 1, "size": "1024x1536", "quality": "medium"}
```

返回是 OpenAI 格式:`data[0].b64_json`。`gemini-3-pro-image` 和 `z-image-turbo` 是这个网关上的其他备选——但实测这个 newapi 部署的 `/v1/images/generations` 只认 `gpt-image-2` 风格和 `imagen` 风格的模型名(试过别的模型名直接 500 报错"only imagen models are supported")——不要假设 `/v1/models` 里列出的模型在每个接口下都能用,批量生成前先测一张。

**`quality` 参数的选择很关键**:`"high"` 在这个网关上稳定地在跑了5-10分钟之后被网关自己的服务端超时打断(504 Gateway Timeout,比你客户端设的任何超时都短,重试也没用),`"medium"` 是实测可靠的默认档位,画质依然很好(章鱼哥、珊迪那两张参考图都是用 medium 生成的,细节和辨识度都不差)。真需要 high 画质的话,预期要接受明显的失败率,并且脚本要做好单场景失败不影响其余场景的容错(逐场景 try/except,不要让一次超时炸掉整批)。

如果这个内容系列已经有过参考风格图(比如查一下源素材所在文件夹),先看一眼再写提示词,让人物/画风描述跟已有的视觉语言保持一致,而不是自己瞎猜风格。

## 阶段3 —— 场景视频生成(共享 ComfyUI 集群上的 MiniMax H3)

这是开发过程中反复出问题的阶段。动手之前把这一整节看完。

### 这个集群不是看上去的样子

`{COMFYUI_HOST}:{MASTER_PORT}` 加7个 worker 端口,是一套 **ComfyUI-Distributed** 部署(github.com/robertvoy/ComfyUI-Distributed),不是8台碰巧共享主机的独立 ComfyUI 服务器。它有一套真实的主从协议(`POST /distributed/queue`、通过 websocket 探测 worker 健康状态、自动给 worker 同步媒体文件)——但每个 worker 本身*同时也*是一个普通的 ComfyUI 实例,会直接接受裸的 `POST {worker}/prompt`,完全绕开这套协议。这样做安不安全,得看运气:在这个项目的历史上,直接给 worker 提交第一次是正常执行的,后来却跟这些 worker 之后反复卡住30分钟以上产生了关联,没有完全查清根因。**默认用只走 master、顺序执行的方式**(`scripts/gen_scene_master_only.py`)——这是两次完整生产跑下来唯一稳定可靠的方式。只有当只走 master 太慢、赶不上截止时间时才去碰真正的并行,如果要碰:对 `gen_scene_master_only.py` 里的 `run_scene()` 函数,每个场景对着不同的端口(它可选的第4个命令行参数)各起一个后台进程手动跑——这里故意没有写一个"一键并行"脚本,因为开发时踩的坑(超时设太短、graph构造的一个真实bug、master自身探测机制的一个真实故障)多到让我觉得包装成一键工具是不负责任的。如果还是要这么做:

- 不要对一个端口上**正在跑任务**的时候调用 `POST /queue {"delete": [...]}`——在这套部署上实测会把那个正在跑的任务一起打断,不只是清掉排队中的任务。
- 给任务留**足够长**的超时(2小时,不是30分钟)再判定它死了。这个集群上的并发负载会实实在在地拖慢每一个参与者(单独跑8分钟的任务,5个一起跑可能要35分钟以上)——这不等于卡死,对一个变慢但仍在真实运行的任务喊 `/interrupt`,等于把已经付出的真实 GPU 算力全部扔掉。真要判断之前,先用 `GET /system_stats`(显存占用是不是在真实变化,不是长期停在0)或者 `GET /history/{prompt_id}` 确认一下。
- `POST /distributed/queue` 才是把*单个* workflow 分发给多个 worker 的正确方式(通过 `DistributedValue`/`DistributedSeed`/`DistributedCollector` 节点——`scripts/distributed_submit.py` 有一个完整可用的例子,包括怎么通过 `GET /distributed/config` 查到 worker 的真实 UUID)。开发过程中遇到过它自己的 worker 健康探测报告"0个活跃worker"、而实际上每个 worker 都能连通的情况——大概率是运行了很久的 master 进程自身连接池耗尽导致的。如果你请求了 worker 却看到 `worker_count: 0`,那是 master 进程本身的问题,不是你的请求写错了;重启 master 能清掉,但你大概率没有权限远程重启。

### 帧数长度限制

`MiniMaxH3ImageToVideo` 的 `length` 参数接受最大 3600,但它*训练时*的范围文档写的是约124-362帧,实际测试中,单次生成调用在48GB显卡上超过大约 **280帧** 时会稳定地 OOM,哪怕这张卡完全空闲、只跑这一个任务——这是跟帧数绑定的真实单任务显存上限,不是排队造成的假象。280帧以内的场景:直接生成,把该场景阶段2的参考图设为 `first_frame`。需要更长的场景:拆成两段——

1. **A段**:长度 ≤260,用该场景阶段2的参考图作为 `first_frame`。
2. 提取A段实际的最后一帧(`ffmpeg -sseof -1 -i partA.mp4 -update 1 -q:v 2 last.png`——这样才能可靠拿到真正的最后一帧,而不是近似定位),通过 `POST /upload/image` 上传(multipart,字段名是 `image`)。
3. **B段**:长度 ≤260,用刚提取的那一帧作为 `first_frame`(是在延续这个镜头,不是重新开始一个镜头),然后用 ffmpeg concat 把两段接起来。

`MiniMaxH3ImageToVideo` 的 `first_frame` 和 `last_frame` 是**可选的 IMAGE 类型输入**——先用 `GET /object_info/MiniMaxH3ImageToVideo` 查它当前的真实 schema,不要凭假设写字段名;节点 schema 在不同部署之间会有差异。对一个"链接型"输入传一个裸文件名字符串而不是 `[node_id, output_slot]` 这样的链接,会报 `400`,而且只有读 `urllib.error.HTTPError.read()` 里的响应体才能看懂是哪里错了,单看异常信息看不出来。

`scripts/gen_scene_master_only.py <场景号> <A段长度> <B段长度> <端口>` 处理了单个场景的整条链路(提交→等待→抽帧→上传→提交B段→拼接→写回结果);除非你已经读过上面这一节、并且是有意要并行,否则就一个场景一个场景顺序跑,都走 master 端口。

## 阶段4 —— PalmierPro 装配

用 `palmier-pro` 这个 MCP 工具集(`get_timeline`、`import_media`、`add_clips`、`set_clip_properties`)。下面是从一条28分镜的生产时间线里总结出来的精确摆放数学:

1. `import_media` 导入每个场景最终生成的 mp4。
2. `add_clips` 放到该场景目标的 `startFrame`(项目帧数,按*时间线*的 fps 算——不是素材原始的 fps;Palmier 会先按素材原生时长摆放,如果跟时间线 fps 不一致会给出提示,而这些素材基本都是24fps渲染的,几乎每次都会不一致)。
3. 计算 `speed = (素材实际时长秒数 × 时间线fps) / 目标时长帧数`,然后对同一个clip调用 `set_clip_properties(speed=..., durationFrames=目标时长帧数)`——这样不管模型实际渲染出多长,都能精确落在目标帧区间里。显式传 `durationFrames`(不是只传 `speed`)可以避免"没按生成顺序摆放clip时,add_clips的自动裁剪重叠逻辑"带来的偏差。
4. 在单独的轨道上加字幕/旁白(`add_captions`、音频轨的 `add_clips`),用阶段1里每个场景实测的 TTS 时长和 SRT 时间码。**字幕不要一个场景一整句话地放成一条caption**——一整句话在1088px宽的竖屏画布上大概率会自动换行成2-3行,看起来很挤(实际遇到过);把每个场景的旁白按标点切成短句(`scripts/gen_srt.py` 已经这样处理),每条字幕停留的时长按这条短句的字数占整场景时长的比例分配,这样短句总时长永远精确等于该场景的真实音频时长,不会跟旁白错位。
5. 重新读一遍 `get_timeline`,检查视频轨道的 `gaps` 列表——如果每个场景都放上了,应该是空的(或 `[]`)。gaps列表不为空能精确定位到底是哪个场景没装配上——开发过程中真实抓到过一个bug:有个场景生成好几个小时了,一直没人导入进时间线。不要以为"生成完成"就等于"装配完成";一定要检查gaps列表。

**字幕想要强调色/卡拉OK质感,先试 Palmier 自己的 `update_text`**(`animation: "highlightPop"` 或 `"highlightBlock"` + `highlightColor: "#hex"`),不必一上来就跳到阶段6的 HyperFrames 路线——这是可编辑的原生能力,改字体/颜色/时机都是一次工具调用,不用重新走一遍渲染管线。**但要注意它是整条caption(一个短句)一起变色,不是逐字轮流点亮某一个字、其余变灰**——实测 `highlightPop`/`highlightBlock` 在同一个caption clip的整个显示区间内,可见文字全部一起呈现高亮色(配合逐字pop-in的入场动效),没有"当前字高亮、其余字保持底色"的指针式效果。如果确实需要那种逐字轮动的指针效果,原生字幕做不到,才需要阶段6。另外调大 `fontSize` 时留意最长的那条短句会不会顶到画布边缘被裁切(1088px宽的竖屏画布上,14个字左右的短句在 `fontSize` 超过约48-50时就可能溢出,需要实际截帧 `capture_frame`+`inspect_media` 看一眼,不要只看返回的数值确认没报错就当作没问题)。

关于配乐(BGM):这套流程目前没有配乐生成模型可用(查过 newapi 的 `/v1/models`,没有任何音乐生成相关的模型)。如果需要BGM,要么接入一个正版授权的音乐库/服务,要么由用户提供自己的曲目——不要凭感觉从网上随便下载一段来源不明的音乐,版权风险自己判断不了就不要替用户做这个决定。

## 阶段5 —— 导出

`export_project(mode="video", codec="H.264", resolution="Match Timeline")`。默认写到 `~/Downloads/<项目名>.mp4`。完成后会有系统通知,不需要为了等进度去反复轮询 `manage_exports`。

## 语音合成(TTS)—— 默认免费方案,按需切换

`scripts/gen_tts.py` 支持两种后端,通过命令行参数选择,默认 `edge`:

- **`edge`(默认)**:`edge-tts`,微软 Edge 内置的免费神经网络语音,不需要 API key,不花钱。日常使用和大多数正式产出场景够用。需要先 `pip install edge-tts`。默认音色 `zh-CN-YunjianNeural`(男声,偏活力,适合财经/科普类口播),其他可选中文音色:`zh-CN-XiaoxiaoNeural`/`XiaoyiNeural`(女声)、`YunxiNeural`/`YunxiaNeural`/`YunyangNeural`(男声,风格各不相同)。
- **`newapi`**:通过 newapi 网关调 `qwen3-tts-base`(付费,用 `NEWAPI_KEY`)。当你确实需要这个特定音色/模型,或者 edge-tts 在你的网络环境里被墙时用这个。这个网关的 key 检查下来只开通了 `zora` 这一个音色——遇到400就读一下报错内容,里面会列出实际能用的音色。

两种后端语速不同(实测 edge-tts 比 qwen3-tts-base 语速略快),换后端之后要重新跑一遍阶段4的装配数学,不能沿用旧的 tts_duration。

## 这个部署上确认可用的模型(直接测过,不是猜的)

- 文案/提示词写作:`claude-opus-4-8`、`gpt-5.2`、`gemini-3.5-flash`(随便一个强文本模型都行,没有特殊要求)
- 看图/逆向还原源视频:`gemini-3-pro-image-preview` 或 `gemini-2.5-pro`(原生支持多图输入)
- 首帧图:`gpt-image-2`(确认可用,画质好);`gemini-3-pro-image` 和 `z-image-turbo` 是备选,没有端到端测过
- TTS:见上一节
- 视频生成:走上面说的 ComfyUI 集群上的 MiniMax H3,不是这个网关

用之前拿 `GET {NEWAPI_URL}/v1/models` 重新核实一遍这份清单——网关会增删模型。

## 阶段6(可选) —— HyperFrames 卡拉OK字幕升级

**先看阶段4末尾那条 Palmier 原生字幕的说明——多数"想要好看一点的字幕强调效果"的需求,`update_text` 就够了,不需要走到这一步。** 只有确实需要"当前这一个字高亮、其余字保持底色"的逐字指针效果(Palmier 原生字幕做不到,它是整句一起变色),或者需要比 Palmier 文字层能力更复杂的运动设计时,才值得投入阶段6的额外工具链和渲染成本。

阶段5导出成片之后的纯后处理:把导出的 mp4 当底层视频,叠加一层用真实逐字时间戳驱动的卡拉OK字幕(逐字高亮+hard-kill消失),用 `npx hyperframes render` 出最终成片。这条路径渲染出来的字幕是**烧录在画面像素里的,后续没法再用 Palmier 的字幕工具调整**——如果预期文案/样式还要反复改,更适合先用阶段4的原生字幕方案迭代,定稿后再考虑要不要走这一步。不碰 PalmierPro 工程本身,不需要就完全跳过。

**已经在真实视频上完整跑通并验证**(不是纯推演):`npx hyperframes check` 在真实的28.3秒 Bikini Bottom 成片上跑出 lint/runtime/layout/motion 全部0错误、对比度21/21通过WCAG AA,`render --quality draft` 74.7秒渲染完成(22.1MB)。跑的过程中修正过几个实现细节,都在下面列出,不要凭直觉重新踩一遍。

### 前置条件

Node ≥22、FFmpeg、Chrome(`npx hyperframes doctor` 先检查)。不需要新的 API key——这一整阶段完全本地免费跑(`newapi` 只在阶段1用了这个TTS后端时,才会在下面的 fallback 脚本那一步间接涉及,这一阶段本身不调用它)。**首次 `npx hyperframes init` 会自动跑一次"对照GitHub检查skills"的网络请求,实测遇到过卡死不动的情况**——脚本里已经设置了 `HYPERFRAMES_SKIP_SKILLS=1` 环境变量绕开它,手动跑CLI时如果卡在"Cloning repository..."也用这个环境变量重试。

### 步骤

1. `scripts/gen_tts.py`(阶段1用的同一个脚本)默认的 `edge` 后端现在会顺带免费拿到字级时间戳,写入每个场景的 `word_timestamps`。如果某些场景是用 `newapi` 后端配的音,跑 `scripts/gen_word_timestamps_fallback.py <scenes.json>` 补上(本地 Whisper,免费)——**中文必须显式传 `--model large-v3 --language zh`**,CLI 自己的默认值 `small.en` 是纯英文模型,中文音频会被强行按英文解码或者直接翻译成英文,不是转写。**这条 fallback 路径实测很慢**——`large-v3` 在纯CPU(无GPU加速)的机器上,一段5-6秒的音频跑了1分多钟还没出结果,场景数多的话这一步要预留足够时间,别指望它跟 `edge` 后端一样是几秒钟的事。
2. `scripts/build_karaoke_transcript.py <scenes.json> <timeline_fps> <out_dir>` 把每个场景的字级时间戳投影到整片绝对时间轴,按标点切句分组,输出 `caption_groups.json`。
3. `scripts/gen_karaoke_composition.py <caption_groups.json> <导出mp4路径> <project_dir>` 生成完整的 HyperFrames 项目(自动 `init`、写 `index.html`、跑 `npx hyperframes check`)。
4. Check 通过后,`cd <project_dir> && npx hyperframes render --quality draft` 出一版草稿,确认没问题再用 `--quality high` 出终版。

### 写覆盖层时踩过的坑(手写 `index.html` 时对照)

- **每组字幕的 `data-start`/`data-duration` 必须精确等于它自己 GSAP 时间线上"可见"的那段区间,不能加提前量**——比如为了让淡入动画提前0.1秒开始,把 `data-start` 也提前0.1秒,会导致这组字幕的挂载窗口跟前一组字幕的挂载窗口在同一个 track 上重叠,`lint` 会报 `overlapping_clips_same_track`。且不要指望"反正只是提前0.1秒,GSAP 早晚会补上"——DOM 元素在挂载窗口之外根本不存在,GSAP 动画不到它。
- `<video>` 元素本身也要写 `data-start="0"`,漏了会报 `media_missing_data_start`。
- 用到非系统自带字体(比如为中文指定 `Noto Sans SC`)要么真的声明 `@font-face` 指向下载好的字体文件,要么用 `src: local("PingFang SC")` 这种系统字体名"过关"——什么都不声明会报 `font_family_without_font_face`,渲染时会 silently 掉到某个默认字体。
- 高亮态的纯白文字在视频背景较亮的片段上,WCAG对比度检查会不过——加一圈实心黑色描边(4个方向各3px的 `text-shadow` + 一层模糊阴影)比单纯调灰度更管用,而且不需要针对每个场景单独判断背景亮度。
- 这套阶段6的脚本目前是针对"整段视频前后拼接、没有连续人物主体"的AI生成动画内容设计的手写覆盖层方案。HyperFrames 生态里还有一个专门的 `/embedded-captions` 工作流(带人物抠像、能把字嵌到人物身后),**那个不适用这里**——它自己的 decision gate 会因为"没有人物主体"或者"素材本来就有硬切镜头"直接拒绝处理,这是它的设计前提决定的,不是配置错了。
