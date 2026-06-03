import requests
import json
from pathlib import Path

OUTPUT_PATH = Path(__file__).resolve().parent / "sample_docred.json"

def download_via_cdn():
    print("🚀 正在通过 jsDelivr 全球加速 CDN 直连拉取清华 DocRED 官方数据（免代理模式）...")
    
    # 使用 jsDelivr CDN 镜像直接穿透，无需配置任何 local proxy 端口
    cdn_url = "https://cdn.jsdelivr.net/gh/thunlp/DocRED@master/data/dev_rev.json"
    
    try:
        print(f"正在请求 CDN 通道: {cdn_url}")
        # 彻底不带 proxies 参数，直连国内满速下载
        resp = requests.get(cdn_url, timeout=30)
        resp.raise_for_status()
        
        all_data = resp.json()
        print(f"✅ 下载成功！总共获取到 {len(all_data)} 篇文档。")
        
        # 截取前 3 篇作为本地联调样本
        preview_docs = all_data[:3]
        samples = []
        for i, doc in enumerate(preview_docs):
            samples.append({
                "document_id": str(doc.get("title", f"doc_{i}")),
                "raw_text": "\n".join([" ".join(sent) for sent in doc.get("sents", [])]),
                "vertexSet": doc.get("vertexSet", []),
                "labels": doc.get("labels", [])
            })
            
        payload = {
            "dataset": "DocRED",
            "split": "dev_rev",
            "sample_count": len(samples),
            "samples": samples,
        }
        
        OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"🎉 黄金样本已完美保存至: {OUTPUT_PATH}")
        
    except Exception as e:
        print(f"❌ CDN 下载失败: {e}")
        print("💡 应急 Plan B：请直接在浏览器打开上述 CDN 链接，全选复制内容，在 scripts 目录下手动新建 sample_docred.json 粘贴保存即可！")

if __name__ == "__main__":
    download_via_cdn()