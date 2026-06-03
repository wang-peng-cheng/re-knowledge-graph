import json
from pathlib import Path

def generate_mock_docred():
    print("🚀 正在生成 1:1 还原的 DocRED 黄金标准样本...")
    
    # 这是 DocRED 真实的极其严苛的 JSON 结构
    sample_data = [
        {
            "title": "成都市锦江区草编活动",
            # sents: 文档被切分成句子，每个句子又被切分成 Token（词）列表
            "sents": [
                ["中", "国", "侨", "网", "成", "都", "11", "月", "19", "日", "电", "。"],
                ["“", "编", "织", "千", "年", "绿", "意", "”", "活", "动", "在", "成", "都", "举", "行", "。"]
            ],
            # vertexSet: 实体列表，每个实体包含它在文中的所有提及(mentions)
            "vertexSet": [
                [
                    {"name": "中国侨网", "pos": [0, 4], "sent_id": 0, "type": "ORG"},
                    {"name": "侨网", "pos": [2, 4], "sent_id": 0, "type": "ORG"}
                ],
                [
                    {"name": "成都", "pos": [4, 6], "sent_id": 0, "type": "LOC"},
                    {"name": "成都", "pos": [11, 13], "sent_id": 1, "type": "LOC"}
                ]
            ],
            # labels: 关系列表（黄金标准），包含头实体索引(h)、尾实体索引(t)、关系ID(r)和证据句子(evidence)
            "labels": [
                {
                    "r": "P17",  # P17 在维基数据中代表 "国家" 或 "位于"
                    "h": 0,      # 头实体：中国侨网 (vertexSet[0])
                    "t": 1,      # 尾实体：成都 (vertexSet[1])
                    "evidence": [0] # 证据在第0句话
                }
            ]
        }
    ]

    output_path = Path(__file__).resolve().parent.parent / "sample_docred.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sample_data, f, ensure_ascii=False, indent=2)
        
    print(f"🎉 生成成功！请查看 {output_path}。这正是明后天咱们要做准确率对比的目标格式！")

if __name__ == "__main__":
    generate_mock_docred()