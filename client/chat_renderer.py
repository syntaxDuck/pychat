import logging
from blessed import Terminal
from enum import Enum
from pydantic import BaseModel
from shared.models import Message


class Color(Enum):
    BLACK = (0, 0, 0)
    WHITE = (255, 255, 255)
    RED = (255, 0, 0)
    GREEN = (0, 255, 0)
    BLUE = (0, 0, 255)


class ChatRenderConfig(BaseModel):
    background_color: Color = Color.WHITE
    border_color: Color = Color.BLACK
    input_marker: str = ">"
    input_border_symbol: str = "─"
    space_between_messages: int = 2
    user_identifier: str = "Me"


class ChatRenderer:
    def __init__(
        self,
        config: ChatRenderConfig = ChatRenderConfig(),
    ):
        self._term: Terminal
        self.render_config: ChatRenderConfig = config
        self.logger = logging.getLogger("chat_renderer")

        self.y_offset: int = 0
        self.input_box_height: int = 1

    @property
    def term(self) -> Terminal | None:
        return self._term

    @term.setter
    def term(self, value: Terminal):
        if not isinstance(value, Terminal):
            raise TypeError("term must be an instance of blessed.Terminal")
        self._term = value

    def render_user_interface(self, input_buffer: str, message_history: list[Message]):
        try:
            self.y_offset = 0
            self.clear()
            self.render_input_box(input_buffer)
            self.render_messages(message_history)

        except Exception as e:
            self.logger.error(f"Error in broadcast handler: {e}")
            raise

    def render_input_box(self, input_buffer: str = ""):
        bar_height = 2
        input_marker_size = len(self.render_config.input_marker) + 1
        input_space = self._term.width - input_marker_size - 2
        extra_lines = len(input_buffer) // input_space

        print(
            self._term.move_xy(0, self._term.height - extra_lines - bar_height)
            + self._term.color_rgb(
                *self.render_config.border_color.value,
            )
            + self.render_config.input_border_symbol * self._term.width
            + self._term.move_down(1)
            + self._term.move_left(self._term.width)
            + self.render_config.input_marker
            + " ",
            end="",
            flush=True,
        )
        self.render_user_input(input_space, extra_lines, input_buffer)

    def render_user_input(self, input_space: int, extra_lines: int, input_buffer: str):
        input = []
        for x in range(0, len(input_buffer), input_space):
            input.append(input_buffer[x : x + input_space])
        input = "\n  ".join(input)

        print(
            self._term.move_xy(2, self._term.height - extra_lines - 1)
            + input
            + self._term.clear_eol,
            end="",
            flush=True,
        )

    def render_messages(self, message_history: list[Message]):
        for message in message_history:
            if message.origin == "localhost":
                user_marker = f"{self.render_config.user_identifier}: "
                user_message = user_marker + message.content
                offset = len(user_message)
                formatted_message = " " * (self._term.width - offset) + user_message
            else:
                formatted_message = f"{message.origin}┠─ {message.content}"
            print(
                self._term.move_xy(0, self.y_offset)
                + formatted_message
                + self._term.clear_eol,
                end="",
                flush=True,
            )
            self.y_offset += self.render_config.space_between_messages

    def clear(self):
        print(
            self._term.home
            + self._term.on_color_rgb(*self.render_config.background_color.value)
            + self._term.clear
        )
