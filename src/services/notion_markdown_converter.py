"""
Markdown to Notion Blocks Converter

使用 mistletoe 解析 Markdown 并转换为 Notion API blocks
支持：加粗、斜体、删除线、内联代码、嵌套列表等
"""

from typing import List, Dict, Any
from mistletoe import Document
from mistletoe.base_renderer import BaseRenderer
import mistletoe.block_token as block_token
import mistletoe.span_token as span_token


class NotionRenderer(BaseRenderer):
    """
    Notion API 渲染器

    将 Markdown AST 转换为 Notion API blocks
    """

    def __init__(self):
        super().__init__()
        self.blocks = []

    def render(self, token) -> List[Dict[str, Any]]:
        """渲染入口"""
        self.blocks = []
        self._render_token(token)
        return self.blocks

    def _render_token(self, token):
        """渲染单个token"""
        if isinstance(token, block_token.Document):
            self.render_document(token)
        elif isinstance(token, block_token.Heading):
            self.render_heading(token)
        elif isinstance(token, block_token.Paragraph):
            self.render_paragraph(token)
        elif isinstance(token, block_token.CodeFence):  # mistletoe uses CodeFence, not BlockCode
            self.render_code_fence(token)
        elif isinstance(token, block_token.BlockCode):
            self.render_block_code(token)
        elif isinstance(token, block_token.List):
            self.render_list(token)
        elif isinstance(token, block_token.Quote):
            self.render_quote(token)
        elif isinstance(token, block_token.ThematicBreak):
            self.render_thematic_break(token)
        elif isinstance(token, block_token.Table):
            self.render_table(token)
        # 其他类型忽略或记录警告
        return None

    # ============= Block-level tokens =============

    def render_document(self, token: block_token.Document) -> None:
        """渲染文档（根节点）"""
        for child in token.children:
            self._render_token(child)

    def render_heading(self, token: block_token.Heading) -> None:
        """渲染标题"""
        level = token.level

        # Notion 只支持 heading_1, heading_2, heading_3
        if level > 3:
            level = 3

        heading_type = f"heading_{level}"

        rich_text = self._render_inline_tokens(token.children)

        self.blocks.append({
            "object": "block",
            "type": heading_type,
            heading_type: {
                "rich_text": rich_text
            }
        })

    def render_paragraph(self, token: block_token.Paragraph) -> None:
        """渲染段落"""
        rich_text = self._render_inline_tokens(token.children)

        if not rich_text:
            return

        self.blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": rich_text
            }
        })

    def render_code_fence(self, token: block_token.CodeFence) -> None:
        """渲染代码块（CodeFence - 三个反引号包围的代码）"""
        language = token.language or "plain text"

        # CodeFence 的内容在 children[0].content
        content = ""
        if token.children and len(token.children) > 0:
            content = token.children[0].content[:2000]

        self.blocks.append({
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": content}
                }],
                "language": self._map_language(language)
            }
        })

    def render_block_code(self, token: block_token.BlockCode) -> None:
        """渲染代码块（BlockCode - 缩进的代码块）"""
        language = token.language or "plain text"

        self.blocks.append({
            "object": "block",
            "type": "code",
            "code": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": token.children[0].content[:2000]}
                }],
                "language": self._map_language(language)
            }
        })

    def render_list(self, token: block_token.List) -> None:
        """渲染列表（有序/无序）"""
        for item in token.children:
            self._render_list_item(item, token.start is not None)

    def _render_list_item(self, token: block_token.ListItem, ordered: bool = False) -> None:
        """
        渲染列表项（关键：支持嵌套）

        Args:
            token: ListItem token
            ordered: 是否为有序列表
        """
        # 分离主内容和嵌套列表
        main_content = []
        nested_blocks = []

        for child in token.children:
            if isinstance(child, block_token.List):
                # 嵌套列表 - 递归处理
                old_blocks = self.blocks
                self.blocks = []
                self.render_list(child)
                nested_blocks.extend(self.blocks)
                self.blocks = old_blocks
            elif isinstance(child, block_token.Paragraph):
                # 段落内容
                main_content.extend(self._render_inline_tokens(child.children))
            else:
                # 其他内联元素
                if hasattr(child, 'children'):
                    main_content.extend(self._render_inline_tokens(child.children))

        # 如果没有主内容，使用空文本
        if not main_content:
            main_content = [{"type": "text", "text": {"content": " "}}]

        # 构建列表项
        list_type = "numbered_list_item" if ordered else "bulleted_list_item"

        block = {
            "object": "block",
            "type": list_type,
            list_type: {
                "rich_text": main_content[:100]  # Notion 限制
            }
        }

        # 添加嵌套列表
        if nested_blocks:
            block[list_type]["children"] = nested_blocks[:100]  # Notion 限制

        self.blocks.append(block)

    def render_quote(self, token: block_token.Quote) -> None:
        """渲染引用块"""
        # 收集引用内容
        rich_text = []
        for child in token.children:
            if isinstance(child, block_token.Paragraph):
                rich_text.extend(self._render_inline_tokens(child.children))

        if not rich_text:
            return

        self.blocks.append({
            "object": "block",
            "type": "quote",
            "quote": {
                "rich_text": rich_text[:100]  # Notion 限制
            }
        })

    def render_thematic_break(self, token: block_token.ThematicBreak) -> None:
        """渲染分隔线"""
        self.blocks.append({
            "object": "block",
            "type": "divider",
            "divider": {}
        })

    def render_table(self, token: block_token.Table) -> None:
        """渲染表格 - Notion API 支持表格，但实现复杂，暂时转为文本"""
        # TODO: 实现完整的表格支持
        self.blocks.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{
                    "type": "text",
                    "text": {"content": "[表格内容 - 暂不支持]"}
                }]
            }
        })

    # ============= Inline tokens (span) =============

    def _render_inline_tokens(self, tokens) -> List[Dict[str, Any]]:
        """
        渲染内联 token 列表

        返回 Notion rich_text 数组
        """
        result = []

        for token in tokens:
            rendered = self._render_inline_token(token)
            if rendered:
                if isinstance(rendered, list):
                    result.extend(rendered)
                else:
                    result.append(rendered)

        return result

    def _render_inline_token(self, token) -> Any:
        """渲染单个内联 token"""

        # 纯文本
        if isinstance(token, span_token.RawText):
            return {
                "type": "text",
                "text": {"content": token.content},
                "annotations": self._default_annotations()
            }

        # 加粗 **text**
        elif isinstance(token, span_token.Strong):
            content = self._extract_text_content(token.children)
            return {
                "type": "text",
                "text": {"content": content},
                "annotations": {
                    **self._default_annotations(),
                    "bold": True
                }
            }

        # 斜体 *text*
        elif isinstance(token, span_token.Emphasis):
            content = self._extract_text_content(token.children)
            return {
                "type": "text",
                "text": {"content": content},
                "annotations": {
                    **self._default_annotations(),
                    "italic": True
                }
            }

        # 删除线 ~~text~~
        elif isinstance(token, span_token.Strikethrough):
            content = self._extract_text_content(token.children)
            return {
                "type": "text",
                "text": {"content": content},
                "annotations": {
                    **self._default_annotations(),
                    "strikethrough": True
                }
            }

        # 内联代码 `code`
        elif isinstance(token, span_token.InlineCode):
            return {
                "type": "text",
                "text": {"content": token.children[0].content},
                "annotations": {
                    **self._default_annotations(),
                    "code": True
                }
            }

        # 链接 [text](url)
        elif isinstance(token, span_token.Link):
            content = self._extract_text_content(token.children)
            return {
                "type": "text",
                "text": {
                    "content": content,
                    "link": {"url": token.target}
                },
                "annotations": self._default_annotations()
            }

        # 图片 ![alt](url) - Notion 不支持内联图片
        elif isinstance(token, span_token.Image):
            # 返回链接文本
            return {
                "type": "text",
                "text": {"content": f"[图片: {token.title or token.target}]"},
                "annotations": self._default_annotations()
            }

        # 换行
        elif isinstance(token, span_token.LineBreak):
            return {
                "type": "text",
                "text": {"content": "\n"},
                "annotations": self._default_annotations()
            }

        # 其他类型（递归处理子元素）
        elif hasattr(token, 'children'):
            return self._render_inline_tokens(token.children)

        return None

    def _extract_text_content(self, tokens) -> str:
        """从 token 列表中提取纯文本"""
        result = []
        for token in tokens:
            if isinstance(token, span_token.RawText):
                result.append(token.content)
            elif hasattr(token, 'children'):
                result.append(self._extract_text_content(token.children))
        return ''.join(result)

    def _default_annotations(self) -> Dict[str, Any]:
        """默认的文本注解"""
        return {
            "bold": False,
            "italic": False,
            "strikethrough": False,
            "underline": False,
            "code": False,
            "color": "default"
        }

    def _map_language(self, lang: str) -> str:
        """映射语言名称到 Notion 支持的语言"""
        # Notion 支持的语言映射
        lang_map = {
            "py": "python",
            "js": "javascript",
            "ts": "typescript",
            "sh": "shell",
            "bash": "shell",
            "yml": "yaml",
            # 可以添加更多映射
        }

        lang_lower = lang.lower()
        return lang_map.get(lang_lower, lang_lower)


def markdown_to_notion_blocks(markdown_text: str) -> List[Dict[str, Any]]:
    """
    将 Markdown 文本转换为 Notion API blocks

    Args:
        markdown_text: Markdown 文本

    Returns:
        Notion API blocks 列表

    Example:
        >>> blocks = markdown_to_notion_blocks("## Heading\\n\\n**Bold** text")
        >>> print(len(blocks))
        2
    """
    with NotionRenderer() as renderer:
        doc = Document(markdown_text)
        blocks = renderer.render(doc)

    # Notion API 限制：单次创建页面最多 100 个 children blocks
    return blocks[:100]


# 用于测试
if __name__ == "__main__":
    test_md = """
# 标题 1

## 标题 2

这是 **粗体文本** 和 *斜体文本* 还有 ~~删除线~~ 和 `代码`。

- 主列表项 1
- 主列表项 2
  - 嵌套项 2.1
  - 嵌套项 2.2
    - 更深嵌套 2.2.1
- 主列表项 3

1. 有序列表 1
2. 有序列表 2
   - 混合嵌套
   - 另一项

> 这是引用块

---

```python
def hello():
    print("world")
```

[链接文本](https://example.com)
"""

    import json
    blocks = markdown_to_notion_blocks(test_md)
    print(json.dumps(blocks, indent=2, ensure_ascii=False))
