from __future__ import annotations

import logging
import re
from typing import List, Sequence
from uuid import uuid4

from app.domain.models import CleanedTextChunk, RawDocumentRecord

logger = logging.getLogger(__name__)


class TextCleaningService:
    """文本清洗服务实现。

    该服务负责将高噪声、弱结构的原始舆情文本转换为适合大模型稳定消费的
    标准化文本块，并确保 MySQL 数据源中的元数据正确透传到清洗结果中。
    """

    def __init__(self, max_chunk_size: int = 1000, overlap_size: int = 100):
        """初始化文本清洗服务。

        Args:
            max_chunk_size: 单个文本块的最大字符数。
            overlap_size: 文本块之间的重叠字符数，用于保持上下文连续性。
        """
        self.max_chunk_size = max_chunk_size
        self.overlap_size = overlap_size

    async def clean_document(self, record: RawDocumentRecord) -> List[CleanedTextChunk]:
        """执行文档级文本清洗主流程。

        Args:
            record: 原始文档记录对象，包含原始文本和来源元数据。

        Returns:
            List[CleanedTextChunk]: 清洗并切片后的文本块列表。
        """
        logger.info("开始清洗文档: %s", record.document_id)
        
        # 执行文本规整
        normalized_text = await self.normalize_text(record.raw_text)
        
        # 移除模板噪声
        cleaned_text = await self.remove_boilerplate_noise(normalized_text)
        
        # 切分文本块
        chunks = await self.split_into_chunks(record.document_id, cleaned_text)
        
        # 检测时间表达
        chunks_with_time = await self.detect_time_expressions(chunks)
        
        # 透传 MySQL 元数据
        final_chunks = []
        for chunk in chunks_with_time:
            # 构建包含 MySQL 元数据的 metadata 字典
            mysql_metadata = {
                "id": record.metadata.get("id", ""),
                "publish_time": record.metadata.get("publish_time", ""),
                "source": record.metadata.get("source", ""),
                "emotion": record.metadata.get("emotion", ""),
                "city": record.metadata.get("city", ""),
                "original_document_id": record.document_id
            }
            
            # 创建新的 CleanedTextChunk，保留原有属性并更新 metadata
            final_chunk = CleanedTextChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                sequence_no=chunk.sequence_no,
                cleaned_text=chunk.cleaned_text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                detected_time_expressions=chunk.detected_time_expressions,
                metadata={**chunk.metadata, **mysql_metadata}
            )
            final_chunks.append(final_chunk)
        
        logger.info("文档清洗完成，生成 %d 个文本块", len(final_chunks))
        return final_chunks

    async def normalize_text(self, raw_text: str) -> str:
        """执行文本规整与基础去噪。

        Args:
            raw_text: 解析后的原始文本内容。

        Returns:
            str: 完成基础规整后的文本字符串。
        """
        if not raw_text:
            return ""
        
        # 统一编码和换行符
        text = raw_text.replace("\r\n", "\n").replace("\r", "\n")
        
        # 移除多余空白字符
        text = re.sub(r'\s+', ' ', text)
        
        # 移除特殊符号和乱码
        text = re.sub(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]', '', text)
        
        # 移除 HTML 标签
        text = re.sub(r'<[^>]+>', '', text)
        
        return text.strip()

    async def split_into_chunks(self, document_id: str, cleaned_text: str) -> List[CleanedTextChunk]:
        """将清洗后的长文本切分为可抽取的文本块。

        Args:
            document_id: 当前文本所属文档标识。
            cleaned_text: 已完成规整的文档级文本内容。

        Returns:
            List[CleanedTextChunk]: 保留位置偏移和元数据的文本块列表。
        """
        if not cleaned_text:
            return []
        
        chunks = []
        text_length = len(cleaned_text)
        start_pos = 0
        sequence_no = 0
        
        while start_pos < text_length:
            # 计算当前块的结束位置
            end_pos = min(start_pos + self.max_chunk_size, text_length)
            
            # 确保不在句子中间切分
            if end_pos < text_length:
                # 查找最近的句子边界
                sentence_end = cleaned_text.rfind('.', start_pos, end_pos)
                if sentence_end > start_pos and (sentence_end - start_pos) > self.max_chunk_size // 2:
                    end_pos = sentence_end + 1
            
            # 提取文本块内容
            chunk_text = cleaned_text[start_pos:end_pos].strip()
            
            if chunk_text:
                # 创建文本块对象
                chunk = CleanedTextChunk(
                    chunk_id=f"{document_id}_chunk_{sequence_no:04d}",
                    document_id=document_id,
                    sequence_no=sequence_no,
                    cleaned_text=chunk_text,
                    char_start=start_pos,
                    char_end=end_pos,
                    detected_time_expressions=[],
                    metadata={}
                )
                chunks.append(chunk)
                sequence_no += 1
            
            # 移动起始位置，考虑重叠
            start_pos = end_pos - self.overlap_size if end_pos < text_length else end_pos
        
        return chunks

    async def detect_time_expressions(self, chunks: Sequence[CleanedTextChunk]) -> List[CleanedTextChunk]:
        """为文本块补充时间表达识别结果。

        Args:
            chunks: 已完成基础清洗和切片的文本块序列。

        Returns:
            List[CleanedTextChunk]: 已附加时间表达信息的文本块列表。
        """
        # 时间表达式正则模式
        time_patterns = [
            r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
            r'\d{4}/\d{2}/\d{2}',  # YYYY/MM/DD
            r'\d{4}年\d{1,2}月\d{1,2}日',  # 中文日期
            r'\d{1,2}月\d{1,2}日',  # 月日格式
            r'\d{1,2}:\d{2}(?::\d{2})?',  # 时间格式
            r'今天|明天|昨天|前天|后天',  # 相对时间
            r'\d+分钟前|\d+小时前|\d+天前',  # 相对时间表达
            r'\d+年前|\d+个月前|\d+周前',  # 相对时间表达
        ]
        
        updated_chunks = []
        
        for chunk in chunks:
            time_expressions = []
            
            # 使用所有模式检测时间表达
            for pattern in time_patterns:
                matches = re.findall(pattern, chunk.cleaned_text)
                time_expressions.extend(matches)
            
            # 去重并排序
            time_expressions = sorted(list(set(time_expressions)))
            
            # 创建更新后的文本块
            updated_chunk = CleanedTextChunk(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                sequence_no=chunk.sequence_no,
                cleaned_text=chunk.cleaned_text,
                char_start=chunk.char_start,
                char_end=chunk.char_end,
                detected_time_expressions=time_expressions,
                metadata=chunk.metadata
            )
            updated_chunks.append(updated_chunk)
        
        return updated_chunks

    async def remove_boilerplate_noise(self, text: str) -> str:
        """移除网页模板噪声和低价值文本片段。

        Args:
            text: 待处理的原始或规整后文本。

        Returns:
            str: 移除模板噪声后的文本内容。
        """
        if not text:
            return ""
        
        # 常见网页噪声模式
        noise_patterns = [
            r'版权所有[^\n]*',
            r'©[^\n]*',
            r'Copyright[^\n]*',
            r'联系我们[^\n]*',
            r'关于我们[^\n]*',
            r'隐私政策[^\n]*',
            r'使用条款[^\n]*',
            r'备案号[^\n]*',
            r'ICP证[^\n]*',
            r'\d{3}-\d{4}-\d{4}',  # 电话号码
            r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',  # 邮箱
        ]
        
        cleaned_text = text
        
        # 移除所有噪声模式
        for pattern in noise_patterns:
            cleaned_text = re.sub(pattern, '', cleaned_text)
        
        # 移除连续空行
        cleaned_text = re.sub(r'\n{3,}', '\n\n', cleaned_text)
        
        return cleaned_text.strip()