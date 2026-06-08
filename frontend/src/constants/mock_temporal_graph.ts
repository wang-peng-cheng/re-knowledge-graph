import { TemporalEdge, TemporalGraphDataset, TemporalNode } from "@/types/temporal-graph";

const timelineMoments = [
  "2025-01-06T09:00:00Z",
  "2025-01-18T12:00:00Z",
  "2025-02-03T08:30:00Z",
  "2025-02-20T19:10:00Z",
  "2025-03-04T07:45:00Z",
  "2025-03-18T10:15:00Z",
  "2025-04-02T14:20:00Z",
  "2025-04-19T09:40:00Z",
];

const nodes: TemporalNode[] = [
  { id: "p-liu-wei", label: "刘伟", category: "person", stage: "stage_one", validFrom: timelineMoments[0], confidence: 0.93, summary: "调查记者，最早追踪异常资金路径。", chunk: "DocRED-like chunk: 记者刘伟在地方财政披露文件中发现一笔流向不明的专项资金，随后开始追踪相关账户。" },
  { id: "p-chen-rong", label: "陈蓉", category: "person", stage: "stage_one", validFrom: timelineMoments[0], confidence: 0.91, summary: "基金池控制人，与多个资金节点关联。", chunk: "DuIE-like chunk: 陈蓉被描述为海岚资本池的实际控制人，其名字多次与公益拨款审批表共同出现。" },
  { id: "p-zhang-min", label: "张敏", category: "person", stage: "stage_one", validFrom: timelineMoments[2], confidence: 0.88, summary: "救援志愿者，通过直播披露现场偏差。", chunk: "志愿者张敏在洪灾一线直播中提到，仓储物资与公开清单存在差异，并记录了物流车辆编号。" },
  { id: "p-sun-hao", label: "孙昊", category: "person", stage: "stage_one", validFrom: timelineMoments[1], confidence: 0.82, summary: "地方议员助理，参与关键饭局。", chunk: "文本切块指出，孙昊在一次闭门晚宴中与资金审批相关人员同席，时间点早于应急拨款落地。" },
  { id: "p-he-qian", label: "何倩", category: "person", stage: "stage_one", validFrom: timelineMoments[3], confidence: 0.84, summary: "自媒体博主，引爆话题传播。", chunk: "何倩在短视频平台发布夜间船运画面，带动#夜航物资#话题迅速发酵。" },
  { id: "p-wu-fan", label: "吴凡", category: "person", stage: "stage_one", validFrom: timelineMoments[2], confidence: 0.87, summary: "采购负责人，被泄露文件点名。", chunk: "泄露采购表显示，吴凡负责的供应批次存在重复报销与异常加价字段。" },
  { id: "p-gao-lin", label: "高林", category: "person", stage: "stage_one", validFrom: timelineMoments[2], confidence: 0.78, summary: "壳账户持有人，疑似中转角色。", chunk: "多份银行流水摘要将高林列为迅桥账户的登记人，但无法解释其与应急物资项目的业务关系。" },
  { id: "p-tang-jie", label: "唐洁", category: "person", stage: "stage_one", validFrom: timelineMoments[3], confidence: 0.8, summary: "地方通报发言人，尝试稳控舆情。", chunk: "唐洁在仓库失火后的首次发布会上强调事故与物资质量无关，但没有回应仓单缺失问题。" },
  { id: "p-qiao-yu", label: "乔宇", category: "person", stage: "stage_one", validFrom: timelineMoments[6], confidence: 0.86, summary: "外部分析师，为监管立案提供补充证据。", chunk: "分析师乔宇整理出跨平台时间线，指出多起帖子与转账发生在同一小时窗口。" },

  { id: "e-capital-anomaly", label: "专项资金异常", category: "event", stage: "stage_two", validFrom: timelineMoments[0], confidence: 0.95, summary: "舆情源点，异常拨款首次浮现。", chunk: "首轮报道显示，一笔防汛专项资金在到账后48小时内被拆分转出，触发舆论关注。" },
  { id: "e-private-dinner", label: "闭门饭局", category: "event", stage: "stage_two", validFrom: timelineMoments[1], confidence: 0.83, summary: "资金链与地方关系网络开始重叠。", chunk: "照片与定位信息证明，闭门饭局参与者覆盖基金池、物流、地方顾问三方。" },
  { id: "e-flood", label: "临州洪灾", category: "event", stage: "stage_two", validFrom: timelineMoments[2], confidence: 0.96, summary: "突发自然灾害，形成舆情放大器。", chunk: "洪灾爆发后，社会关注迅速聚焦救援效率与救灾物资流向。" },
  { id: "e-fire", label: "仓库失火", category: "event", stage: "stage_two", validFrom: timelineMoments[3], confidence: 0.89, summary: "关键仓储节点损毁，线索出现断裂。", chunk: "失火仓库中存放的部分清单与监控硬盘被毁，引发人为灭证猜测。" },
  { id: "e-procurement-leak", label: "采购单泄露", category: "event", stage: "stage_two", validFrom: timelineMoments[4], confidence: 0.94, summary: "原始文档外泄，关系网络急速扩张。", chunk: "匿名账户上传的采购单中包含批次、报价、审批链和重复合同号。" },
  { id: "e-hashtag-surge", label: "话题冲榜", category: "event", stage: "stage_two", validFrom: timelineMoments[5], confidence: 0.9, summary: "传播层出现疑似操纵与反制。", chunk: "多个相似文本模板在十分钟内集中出现，使相关话题冲上热榜。" },
  { id: "e-regulator-filing", label: "监管立案", category: "event", stage: "stage_two", validFrom: timelineMoments[6], confidence: 0.97, summary: "官方介入，舆情从猜测转向实锤阶段。", chunk: "省级监管机构通报称已就专项资金流向、采购流程与舆情操控同步立案。" },
  { id: "e-detention", label: "留置通报", category: "event", stage: "stage_two", validFrom: timelineMoments[7], confidence: 0.92, summary: "事件进入收束阶段，核心人物失去行动能力。", chunk: "官方深夜通报称，两名关键负责人被留置，后续追责程序已启动。" },

  { id: "f-hailan-pool", label: "海岚资本池", category: "fund", stage: "support", validFrom: timelineMoments[0], confidence: 0.9, summary: "主资金汇集节点。", chunk: "海岚资本池在多个合同中以不同名义出现，但开户信息指向相同控制人。" },
  { id: "f-swift-bridge", label: "迅桥账户", category: "fund", stage: "support", validFrom: timelineMoments[1], confidence: 0.85, summary: "中转账户，承接拆分资金。", chunk: "迅桥账户在饭局曝光后频繁接收小额拆分款项，并迅速流向物流供应商。" },
  { id: "f-relief-wallet", label: "救援电子钱包", category: "fund", stage: "support", validFrom: timelineMoments[4], confidence: 0.77, summary: "新型募资入口。", chunk: "一个标注为公益众筹的电子钱包在采购单曝光后出现大额异常归集。" },
  { id: "f-offshore-batch", label: "离岸回流批次", category: "fund", stage: "support", validFrom: timelineMoments[5], confidence: 0.81, summary: "疑似洗白后的回流资金。", chunk: "跨境转账摘要显示，一组离岸账户在舆情高峰后向海岚资本池分批回流资金。" },

  { id: "s-forum-thread", label: "本地论坛长帖", category: "social", stage: "support", validFrom: timelineMoments[0], confidence: 0.86, summary: "最早形成舆情讨论的社区内容。", chunk: "地方论坛长帖整理了异常拨款表格截图，并引导网友比对公开招投标记录。" },
  { id: "s-media-matrix", label: "自媒体矩阵", category: "social", stage: "support", validFrom: timelineMoments[1], confidence: 0.79, summary: "多账号协同塑造叙事。", chunk: "若干内容近似的账号在不同平台同步发布，统一淡化资金流向问题。" },
  { id: "s-night-boats", label: "夜航物资话题", category: "social", stage: "support", validFrom: timelineMoments[3], confidence: 0.91, summary: "视觉证据触发爆发式传播。", chunk: "夜航画面显示数艘无编号船只卸载标注不明的救援物资，引发大规模转载。" },
  { id: "s-leak-pack", label: "泄露文档包", category: "social", stage: "support", validFrom: timelineMoments[4], confidence: 0.95, summary: "原始证据容器。", chunk: "文档包包含采购表、审批邮件截图及仓单编号，成为后续关联抽取主来源。" },
  { id: "s-live-stream", label: "志愿者直播", category: "social", stage: "support", validFrom: timelineMoments[2], confidence: 0.88, summary: "一线实况，增强事件真实性。", chunk: "直播片段中可见标识冲突的救援箱和排队等待的受灾居民。" },
  { id: "s-bot-cluster", label: "机器人集群", category: "social", stage: "support", validFrom: timelineMoments[5], confidence: 0.82, summary: "异常分发节点，驱动话题冲榜。", chunk: "监测显示，数百个新注册账号在同一时间窗口转发几乎一致的文本模板。" },

  { id: "o-relief-center", label: "临州救援中心", category: "organization", stage: "support", validFrom: timelineMoments[2], confidence: 0.84, summary: "救援调度主体。", chunk: "临州救援中心负责物资调度，但多次对库存缺口解释不一。" },
  { id: "o-east-river", label: "东河物流", category: "organization", stage: "support", validFrom: timelineMoments[2], confidence: 0.83, summary: "异常物流承接方。", chunk: "东河物流在临时扩容后获得大量紧急运单，但车辆轨迹与登记路线不匹配。" },
  { id: "o-harbor-pr", label: "海港公关", category: "organization", stage: "support", validFrom: timelineMoments[1], confidence: 0.76, summary: "疑似舆情干预服务商。", chunk: "合同碎片显示，海港公关在饭局发生后收到一笔标注为声量优化的咨询费。" },
  { id: "o-regulator", label: "省级监管组", category: "organization", stage: "support", validFrom: timelineMoments[6], confidence: 0.93, summary: "最终执法机构。", chunk: "监管组联合通报提到，已锁定采购链、资金链和传播链中的关键节点。" },
];

const edges: TemporalEdge[] = [
  { id: "l-01", source: "p-liu-wei", target: "e-capital-anomaly", relation: "investigates", validFrom: timelineMoments[0], confidence: 0.92, chunk: "刘伟的首篇报道把异常专项资金与防汛预算绑定。" },
  { id: "l-02", source: "p-chen-rong", target: "f-hailan-pool", relation: "controls", validFrom: timelineMoments[0], confidence: 0.94, chunk: "陈蓉被多份资料共同指向海岚资本池控制人。" },
  { id: "l-03", source: "f-hailan-pool", target: "e-capital-anomaly", relation: "triggers", validFrom: timelineMoments[0], confidence: 0.9, chunk: "资本池的异常拆分交易直接触发专项资金异常事件。" },
  { id: "l-04", source: "s-forum-thread", target: "e-capital-anomaly", relation: "amplifies", validFrom: timelineMoments[0], confidence: 0.84, chunk: "论坛长帖帮助资金异常从专业讨论扩散到大众舆论。" },
  { id: "l-05", source: "p-sun-hao", target: "e-private-dinner", relation: "attends", validFrom: timelineMoments[1], confidence: 0.8, chunk: "闭门饭局照片和定位标签确认孙昊在场。" },
  { id: "l-06", source: "p-chen-rong", target: "p-sun-hao", relation: "connected_to", validFrom: timelineMoments[1], confidence: 0.81, chunk: "座次信息显示陈蓉与孙昊在饭局中有直接接触。" },
  { id: "l-07", source: "e-private-dinner", target: "f-swift-bridge", relation: "coordinates", validFrom: timelineMoments[1], confidence: 0.78, chunk: "饭局后迅桥账户出现密集的新入账。" },
  { id: "l-08", source: "o-harbor-pr", target: "s-media-matrix", relation: "operates", validFrom: timelineMoments[1], confidence: 0.77, chunk: "合同碎片将海港公关与多个协同账号关联。" },
  { id: "l-09", source: "s-media-matrix", target: "e-private-dinner", relation: "shapes_narrative", validFrom: timelineMoments[1], confidence: 0.76, chunk: "矩阵账号试图将饭局定性为常规商务社交。" },
  { id: "l-10", source: "p-zhang-min", target: "s-live-stream", relation: "publishes", validFrom: timelineMoments[2], confidence: 0.89, chunk: "张敏通过直播披露救援现场物资错配情况。" },
  { id: "l-11", source: "s-live-stream", target: "e-flood", relation: "authenticates", validFrom: timelineMoments[2], confidence: 0.88, chunk: "直播内容让临州洪灾影响与物资缺口得到验证。" },
  { id: "l-12", source: "p-wu-fan", target: "o-east-river", relation: "oversees", validFrom: timelineMoments[2], confidence: 0.83, chunk: "采购流转单将吴凡标为东河物流对接审批人。" },
  { id: "l-13", source: "p-gao-lin", target: "f-swift-bridge", relation: "holds", validFrom: timelineMoments[2], confidence: 0.79, chunk: "开户文件显示高林为迅桥账户登记人。" },
  { id: "l-14", source: "f-swift-bridge", target: "o-east-river", relation: "funds", validFrom: timelineMoments[2], confidence: 0.82, chunk: "迅桥账户对东河物流完成多笔拆分转账。" },
  { id: "l-15", source: "o-relief-center", target: "e-flood", relation: "responds_to", validFrom: timelineMoments[2], confidence: 0.86, chunk: "救援中心承担洪灾主调度。" },
  { id: "l-16", source: "o-east-river", target: "e-fire", relation: "linked_to", validFrom: timelineMoments[3], confidence: 0.84, chunk: "失火仓库为东河物流临时租赁节点。" },
  { id: "l-17", source: "p-he-qian", target: "s-night-boats", relation: "initiates", validFrom: timelineMoments[3], confidence: 0.9, chunk: "何倩发布夜航物资视频，形成核心话题标签。" },
  { id: "l-18", source: "s-night-boats", target: "e-fire", relation: "amplifies", validFrom: timelineMoments[3], confidence: 0.91, chunk: "夜航物资话题把仓库失火与物资去向放在同一叙事中。" },
  { id: "l-19", source: "p-tang-jie", target: "e-fire", relation: "briefs", validFrom: timelineMoments[3], confidence: 0.75, chunk: "唐洁在失火后的通报会上尝试淡化关联。" },
  { id: "l-20", source: "s-leak-pack", target: "e-procurement-leak", relation: "exposes", validFrom: timelineMoments[4], confidence: 0.95, chunk: "泄露文档包直接引出采购单泄露事件。" },
  { id: "l-21", source: "p-wu-fan", target: "e-procurement-leak", relation: "implicated_in", validFrom: timelineMoments[4], confidence: 0.92, chunk: "采购表中吴凡签批痕迹清晰可见。" },
  { id: "l-22", source: "f-relief-wallet", target: "e-procurement-leak", relation: "surfaces_after", validFrom: timelineMoments[4], confidence: 0.73, chunk: "采购单曝光后，新的电子钱包归集异常被发现。" },
  { id: "l-23", source: "e-procurement-leak", target: "e-hashtag-surge", relation: "catalyzes", validFrom: timelineMoments[5], confidence: 0.89, chunk: "证据文档外泄成为话题冲榜的直接导火索。" },
  { id: "l-24", source: "s-bot-cluster", target: "e-hashtag-surge", relation: "boosts", validFrom: timelineMoments[5], confidence: 0.84, chunk: "机器人集群推动相关词条在短时间内集中放大。" },
  { id: "l-25", source: "f-offshore-batch", target: "f-hailan-pool", relation: "returns_to", validFrom: timelineMoments[5], confidence: 0.8, chunk: "离岸资金在话题冲榜后向海岚资本池批量回流。" },
  { id: "l-26", source: "o-regulator", target: "e-regulator-filing", relation: "files", validFrom: timelineMoments[6], confidence: 0.97, chunk: "省级监管组正式公告立案。" },
  { id: "l-27", source: "e-regulator-filing", target: "p-chen-rong", relation: "targets", validFrom: timelineMoments[6], confidence: 0.93, chunk: "监管立案将陈蓉列为重点调查对象。" },
  { id: "l-28", source: "e-regulator-filing", target: "p-wu-fan", relation: "targets", validFrom: timelineMoments[6], confidence: 0.91, chunk: "吴凡同时进入采购链调查名单。" },
  { id: "l-29", source: "e-regulator-filing", target: "p-gao-lin", relation: "targets", validFrom: timelineMoments[6], confidence: 0.85, chunk: "高林作为账户登记人被一并锁定。" },
  { id: "l-30", source: "p-qiao-yu", target: "e-regulator-filing", relation: "supports", validFrom: timelineMoments[6], confidence: 0.86, chunk: "乔宇提交的时序交叉分析被监管采用。" },
  { id: "l-31", source: "e-regulator-filing", target: "e-detention", relation: "escalates_to", validFrom: timelineMoments[7], confidence: 0.9, chunk: "监管立案后升级为留置通报。" },
  { id: "l-32", source: "e-detention", target: "p-chen-rong", relation: "restricts", validFrom: timelineMoments[7], confidence: 0.88, chunk: "陈蓉在深夜通报后失去公开活动记录。" },
];

export const mockTemporalGraph: TemporalGraphDataset = {
  scenarioTitle: "临州洪灾资金链与舆情操纵联动事件",
  timelineMoments,
  nodes,
  edges,
};

export const timelinePulse = [
  "异常资金被调查记者首次标记，舆情进入潜伏期。",
  "饭局与公关矩阵出现，关系链从资金扩展到传播层。",
  "洪灾爆发，现场直播让抽象风险转为具象危机。",
  "仓库失火与夜航视频叠加，隐含关联开始浮现。",
  "采购单泄露后，多源实体和证据块集中暴露。",
  "话题冲榜，机器人集群与离岸资金形成新联动。",
  "监管立案，图谱从猜测网络转为证据网络。",
  "留置通报发布，关键节点被收束并进入追责阶段。",
];
