import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from ..settings import settings


@dataclass
class TelegramCommunicator:
    """A Telegram-based communicator for trading execution monitoring, converted from C# to Python."""

    program: Any  # Reference to the main execution program (with methods like manual_exit, log)
    token: Optional[str] = None  # Telegram bot API token (optional, uses settings if not provided)
    user_chat_id: Optional[int] = (
        None  # Authorized user's chat ID for this bot (optional, uses settings if not provided)
    )
    last_message: Optional[str] = None  # Last text message received from the user (if any)
    _responses: Dict[str, Callable[[str], None]] = field(default_factory=dict, init=False)
    # The Telegram bot application (from python-telegram-bot). Built in __post_init__.
    application: Optional[Application] = field(init=False, default=None)

    # Class-level newline constant (similar to C# static NewLine)
    NewLine: str = field(default="\n", init=False, repr=False)
    _logger: logging.Logger = field(init=False, repr=False)

    def __post_init__(self):
        """Initializes the Telegram bot application and event handlers."""
        self._logger = logging.getLogger(__name__)
        # Use global settings if token or chat_id not provided
        if not self.token:
            self.token = settings.telegram_bot_token
        if not self.user_chat_id:
            # settings.telegram_chat_id may be a string; coerce to int for filter typing
            raw_chat = settings.telegram_chat_id
            if isinstance(raw_chat, str):
                if raw_chat.isdigit():
                    self.user_chat_id = int(raw_chat)
                else:
                    raise ValueError("TELEGRAM_CHAT_ID must be a numeric chat id (digits only).")
            # raw_chat is configured as Optional[str] in settings; integer branch not needed

        if not self.token:
            raise ValueError(
                "Telegram bot token is required. Set TELEGRAM_BOT_TOKEN environment variable or provide token parameter."
            )
        if not self.user_chat_id:
            raise ValueError(
                "Telegram chat ID is required. Set TELEGRAM_CHAT_ID environment variable or provide user_chat_id parameter."
            )

        # Initialize the Telegram application (event-driven bot).
        assert self.token is not None
        self.application = ApplicationBuilder().token(self.token).build()

        # Add error handler to prevent unhandled exceptions
        async def error_handler(update, context):
            """Log errors caused by Updates."""
            self._logger.error("Telegram error: %s", getattr(context, "error", "<unknown>"))

        self.application.add_error_handler(error_handler)

        # Register a message handler for all text messages.
        # We use filters.TEXT to catch text messages, and filter by chat_id for security.
        # Narrow Optional for the filter API input (expects int)
        assert self.user_chat_id is not None
        msg_handler = MessageHandler(
            filters.TEXT & filters.Chat(chat_id=self.user_chat_id), self._on_message
        )
        assert self.application is not None
        self.application.add_handler(msg_handler)

        # Register a callback query handler for inline button presses.
        cb_handler = CallbackQueryHandler(self._on_callback_query)
        assert self.application is not None
        self.application.add_handler(cb_handler)

        # (Optional) You could add more handlers here (commands, etc.) as needed.

    async def _on_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Internal handler for incoming text messages from the user."""
        text = update.message.text.strip() if update.message and update.message.text else ""
        if not text:
            return  # No text content to process.
        # Only process messages from the authorized user (filters already enforce this).
        # Update the last_message state.
        self.last_message = text
        # Handle special commands (case-insensitive).
        if text.lower() in ("kill", "quit"):
            # A "kill" or "quit" command requests the program to stop.
            # Acknowledge the command and initiate manual exit.
            assert self.user_chat_id is not None
            # Tests may pass a simple Mock for context; support both async & sync
            try:
                send_msg = getattr(context.bot, "send_message", None)
                if send_msg is not None:
                    if asyncio.iscoroutinefunction(send_msg):
                        await send_msg(chat_id=self.user_chat_id, text="Ack Kill")
                    else:
                        # Synchronous fallback for mocked contexts
                        send_msg(chat_id=self.user_chat_id, text="Ack Kill")
            except Exception:
                # Non-fatal notification path; continue shutdown logic
                pass
            if hasattr(self.program, "manual_exit"):
                # Call the program's manual_exit method to stop trading (similar to Program.ManualExit in C#).
                self.program.manual_exit()
            # Mark last_message as "kill" explicitly to reflect the manual override state.
            self.last_message = "kill"
        elif text.lower() in ("exit", "long", "short"):
            # These commands toggle trading mode flags. No immediate action besides logging the state.
            # (The trading program should read is_exit_only, is_long_only, is_short_only flags as needed.)
            self._logger.info("Telegram command received: %s", text)
        else:
            # For any other text, simply log it (or handle accordingly in the program).
            self._logger.info("Telegram message received: %s", text)

    async def _on_callback_query(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Internal handler for incoming callback query (button presses) from inline keyboards."""
        query = update.callback_query
        if query is None:
            return  # No callback query data to process.
        # Acknowledge the callback query to prevent Telegram from showing a "loading" state.
        await query.answer()
        data = query.data  # e.g., "100%::SomeText"
        if not data:
            return
        # Parse the callback data expected in format "Choice::Key"
        if "::" in data:
            choice, key = data.split("::", 1)
        else:
            # If format is unexpected, treat the whole data as key.
            choice, key = data, data
        # Only handle if this key exists in our stored responses.
        if key in self._responses:
            callback_func = self._responses.pop(key)  # Get and remove the stored callback.
            try:
                # Execute the stored callback action with the choice (e.g., "100%", "Cancel", etc.).
                callback_func(choice)
            except Exception as e:
                # Catch exceptions from the callback to avoid crashing the bot loop.
                if hasattr(self.program, "log"):
                    self.program.log(f"Error in Telegram callback response handler: {e}")
        # Optionally, you might edit or remove the inline keyboard after responding. (Not strictly necessary here.)

    def send_text(self, text: str) -> None:
        """
        Send a text message to the user via Telegram.
        This method can be called from the main program to send alerts or info.
        """
        message = text + self.NewLine  # Append a newline (mimicking the C# behavior)
        try:
            # Check if we're in an async context and handle appropriately
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, schedule the coroutine
                assert self.user_chat_id is not None
                assert self.application is not None
                loop.create_task(
                    self.application.bot.send_message(chat_id=self.user_chat_id, text=message)
                )
                # Don't wait for completion to avoid blocking
            except RuntimeError:
                # No running event loop, run in a new loop
                assert self.user_chat_id is not None
                assert self.application is not None
                asyncio.run(
                    self.application.bot.send_message(chat_id=self.user_chat_id, text=message)
                )
        except Exception as e:
            # Log any errors in sending (e.g., if bot is not running or network issues).
            self._logger.warning("Failed to send Telegram message: %s", e)

    def send_choice(self, header: str, key: str, respond: Callable[[str], None]) -> None:
        """
        Send a message with an inline keyboard offering preset choices, and store a response callback.

        :param header: The header or question to display above the inline buttons.
        :param key: A short identifier for this set of responses (used to map the callback).
        :param respond: A function to call with the user's choice when a button is pressed.
        """
        # Show the "typing..." action to let the user know the bot is working.
        try:
            # Handle async call properly
            try:
                loop = asyncio.get_running_loop()
                assert self.user_chat_id is not None
                assert self.application is not None
                loop.create_task(
                    self.application.bot.send_chat_action(
                        chat_id=self.user_chat_id, action=ChatAction.TYPING
                    )
                )
            except RuntimeError:
                assert self.user_chat_id is not None
                assert self.application is not None
                asyncio.run(
                    self.application.bot.send_chat_action(
                        chat_id=self.user_chat_id, action=ChatAction.TYPING
                    )
                )
        except Exception as e:
            self._logger.warning("Failed to send chat action: %s", e)
        # Store the callback for later use when a button is pressed.
        self._responses[key] = respond
        # Build the inline keyboard layout (three rows of two buttons each, as in the original C#).
        keyboard = [
            [
                InlineKeyboardButton("100%", callback_data=f"100%::{key}"),
                InlineKeyboardButton("50%", callback_data=f"50%::{key}"),
            ],
            [
                InlineKeyboardButton("Split 50%", callback_data=f"Split 50%::{key}"),
                InlineKeyboardButton("MOC", callback_data=f"MOC::{key}"),
            ],
            [
                InlineKeyboardButton("Delay", callback_data=f"Delay::{key}"),
                InlineKeyboardButton("Cancel", callback_data=f"Cancel::{key}"),
            ],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        # Compose the message with a newline before and after the header (for formatting, similar to C#).
        text = f"{self.NewLine}{header}{self.NewLine}"
        try:
            # Handle async call properly
            try:
                loop = asyncio.get_running_loop()
                assert self.user_chat_id is not None
                assert self.application is not None
                loop.create_task(
                    self.application.bot.send_message(
                        chat_id=self.user_chat_id, text=text, reply_markup=reply_markup
                    )
                )
            except RuntimeError:
                assert self.user_chat_id is not None
                assert self.application is not None
                asyncio.run(
                    self.application.bot.send_message(
                        chat_id=self.user_chat_id, text=text, reply_markup=reply_markup
                    )
                )
        except Exception as e:
            self._logger.warning("Failed to send choice message: %s", e)

    @property
    def is_exit_only(self) -> bool:
        """True if the last received message was 'exit' (case-insensitive)."""
        return self.last_message is not None and self.last_message.lower() == "exit"

    @property
    def is_long_only(self) -> bool:
        """True if the last received message was 'long' (case-insensitive)."""
        return self.last_message is not None and self.last_message.lower() == "long"

    @property
    def is_short_only(self) -> bool:
        """True if the last received message was 'short' (case-insensitive)."""
        return self.last_message is not None and self.last_message.lower() == "short"

    @property
    def is_manually_overridden(self) -> bool:
        """True if the last received message was 'kill' or 'quit' (manual override to stop the program)."""
        return self.last_message is not None and self.last_message.lower() in ("kill", "quit")

    def start(self, block: bool = False) -> None:
        """
        Start the Telegram bot to begin polling for updates.
        :param block: If True, run the bot in the current thread (blocking). If False (default), run in a background thread.
        """
        assert self.application is not None
        if block:
            # Run the polling in the current thread (this will block until the bot is stopped).
            self.application.run_polling(stop_signals=None)
        else:
            # Run the polling in a separate background thread.
            thread = threading.Thread(target=self._run_polling_async, daemon=True)
            thread.start()

    def _run_polling_async(self) -> None:
        """
        Internal helper to run the bot's polling loop in an asyncio event loop (for background thread usage).
        """
        # Create a new event loop for this thread and set it.
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # Start polling (this will run until stop() is called or program exits).
        assert self.application is not None
        self.application.run_polling(stop_signals=None)
        # When run_polling returns (e.g., after stop), we can close the loop.
        loop.close()

    def stop(self) -> None:
        """Stop the Telegram bot from polling (gracefully shuts down the background thread if running)."""
        # This will signal the Application to stop polling and shut down.
        try:
            # Check if we're in an async context and handle appropriately
            try:
                loop = asyncio.get_running_loop()
                # We're in an async context, schedule the coroutine
                assert self.application is not None
                loop.create_task(self.application.stop())
            except RuntimeError:
                # No running event loop, run in a new loop
                assert self.application is not None
                asyncio.run(self.application.stop())
        except Exception:
            # If that fails, try the shutdown method as fallback
            try:
                try:
                    loop = asyncio.get_running_loop()
                    assert self.application is not None
                    loop.create_task(self.application.shutdown())
                except RuntimeError:
                    assert self.application is not None
                    asyncio.run(self.application.shutdown())
            except Exception:
                # Last resort: just ignore the error
                pass
        # Note: If running in a background thread, the thread will exit once polling stops.
