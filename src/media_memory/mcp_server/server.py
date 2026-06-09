from __future__ import annotations

from dataclasses import dataclass

from media_memory.core.search import SearchService


@dataclass
class MediaMemoryMCPServer:
    search_service: SearchService

    def search_media(self, query: str, limit: int = 10) -> dict[str, object]:
        return {"results": [item.to_dict() for item in self.search_service.search_media(query, limit=limit)]}

    def find_episode(self, query: str, season: int | None = None, episode: int | None = None) -> dict[str, object]:
        return {
            "results": [
                item.to_dict() for item in self.search_service.find_episode(query, season=season, episode=episode)
            ]
        }

    def find_scene(self, query: str, media_path: str | None = None, limit: int = 10) -> dict[str, object]:
        return {"results": self.search_service.find_scene(query, media_path=media_path, limit=limit)}

    def search_dialogue(self, query: str, limit: int = 10) -> dict[str, object]:
        return {"results": self.search_service.search_dialogue(query, limit=limit)}

    def get_scene_context(self, chunk_id: int, window: int = 2) -> dict[str, object]:
        return {"result": self.search_service.get_scene_context(chunk_id=chunk_id, window=window)}

    def call_tool(self, tool_name: str, **kwargs: object) -> dict[str, object]:
        dispatch = {
            "search_media": self.search_media,
            "find_episode": self.find_episode,
            "find_scene": self.find_scene,
            "search_dialogue": self.search_dialogue,
            "get_scene_context": self.get_scene_context,
        }
        if tool_name not in dispatch:
            raise ValueError(
                f"Unknown tool: {tool_name}. Available tools: {', '.join(sorted(dispatch))}"
            )
        return dispatch[tool_name](**kwargs)
