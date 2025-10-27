"""Post entity model representing a Xiaohongshu post."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator


class Post(BaseModel):
    """
    Represents a Xiaohongshu post containing paper information.

    Attributes:
        post_id: Unique identifier for the post (24-character hex string)
        post_url: Full URL to the post
        blogger_name: Name of the blogger who posted
        blogger_id: Unique identifier for the blogger
        raw_content: Raw text content of the post
        published_date: When the post was published (if available)
        images: List of image URLs from the post
        fetched_at: Timestamp when the post was fetched
    """

    post_id: str = Field(
        ...,
        pattern=r"^[a-f0-9]{24}$",
        description="Unique 24-character hex post ID",
    )
    post_url: HttpUrl = Field(
        ...,
        description="Full URL to the Xiaohongshu post",
    )
    blogger_name: Optional[str] = Field(
        None,
        max_length=100,
        description="Name of the blogger",
    )
    blogger_id: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Unique identifier for the blogger",
    )
    raw_content: str = Field(
        ...,
        min_length=1,
        description="Raw text content of the post",
    )
    published_date: Optional[datetime] = Field(
        None,
        description="When the post was published",
    )
    images: list[HttpUrl] = Field(
        default_factory=list,
        description="List of image URLs from the post",
    )
    fetched_at: datetime = Field(
        default_factory=datetime.now,
        description="Timestamp when the post was fetched",
    )

    @field_validator("raw_content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        """Ensure content is not just whitespace."""
        if not v.strip():
            raise ValueError("Post content cannot be empty or whitespace only")
        return v

    class Config:
        """Pydantic configuration."""

        json_schema_extra = {
            "example": {
                "post_id": "5f9e4a2b000000000101a1b2",
                "post_url": "https://www.xiaohongshu.com/explore/5f9e4a2b000000000101a1b2",
                "blogger_name": "大模型知识分享",
                "blogger_id": "467792329",
                "raw_content": "论文标题: Attention Is All You Need\n作者: Vaswani et al.\n摘要: ...",
                "published_date": "2024-10-15T10:30:00",
                "images": ["https://example.com/image1.jpg"],
                "fetched_at": "2024-10-18T14:20:00",
            }
        }
