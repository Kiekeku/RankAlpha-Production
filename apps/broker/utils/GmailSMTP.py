import base64
import hashlib
import os
import smtplib
import socket
from datetime import date, datetime
from email.mime.text import MIMEText
from typing import Any

from apps.broker.utils.DataProtector import DataProtector

try:
    from apps.common.src.email.client import EmailClient  # shared client
except Exception:
    EmailClient = None  # type: ignore

# Import database functionality (optional if dependencies are missing)
select: Any = None
get_session: Any = None
Credential: Any = None
try:
    from sqlalchemy import select as _select
    from tradeexec.database.model import Credential as _Credential
    from tradeexec.database.model import get_session as _get_session

    select = _select
    get_session = _get_session
    Credential = _Credential
    database_available = True
except ImportError as e:
    print(f"Database module not available: {e}")
    database_available = False

# Utility modules not available in this codebase
TypeEnums: Any = None
ZipUtil: Any = None
Settings: Any = None

try:
    from tradeexec.settings import settings as _settings

    settings: Any = _settings
except ImportError:
    settings = None


class GmailSMTP:
    @staticmethod
    def sendEmail(subject, body):
        # Require sender/recipient from settings (env-backed)
        if not settings:
            raise ValueError(
                "Gmail settings not loaded; configure GMAIL_SENDER/GMAIL_RECIPIENT in shared env"
            )
        sender = (settings.gmail_sender or "").strip()
        recipient = (settings.gmail_recipient or "").strip()
        if not sender or not recipient:
            raise ValueError(
                "Gmail sender/recipient not configured; set GMAIL_SENDER and GMAIL_RECIPIENT"
            )

        # format subject line
        machine_name = socket.gethostname()
        formatted_date = datetime.today().strftime("%m/%d/%Y")
        # hash today's date for email
        encrypted_date = base64.b64encode(
            hashlib.md5(date.today().strftime("%m/%d/%Y").encode("utf-8")).digest()
        ).decode("utf-8")

        # Check if body contains HTML tags to determine content type
        if "<html>" in body.lower() or "<body>" in body.lower():
            msg = MIMEText(body, "html")
        else:
            msg = MIMEText(body)
        msg["Subject"] = f"{machine_name}: {subject} {formatted_date} ({encrypted_date})"
        msg["From"] = "Operations <" + sender + ">"
        msg["To"] = "Recipient <" + recipient + ">"

        dataProtector = DataProtector()

        # get credentials from database if available
        password = None
        if (
            database_available
            and get_session is not None
            and Credential is not None
            and select is not None
        ):
            try:
                with get_session() as sess:
                    stmt = select(Credential).where(Credential.Account == "Server1")
                    credential_entry = sess.scalars(stmt).first()

                    if credential_entry:
                        password = dataProtector.decrypt(credential_entry.Password)
                        decrypted_sender = dataProtector.decrypt(credential_entry.UserName)
                        if decrypted_sender:
                            sender = decrypted_sender
            except Exception as e:
                print(f"Failed to get credentials from database: {e}")

        # Fall back to environment variables if database credentials not available
        if password is None:
            password = os.getenv("GMAIL_APP_PASSWORD", "")
            if not password:
                raise ValueError("Gmail password not found in database or environment variables")

        # Reassign the "From" header once we have the real sender
        msg["From"] = f"Operations <{sender or 'unknown@example.com'}>"

        # Prefer shared EmailClient if available; otherwise legacy path
        if EmailClient is not None:
            try:
                EmailClient.send(to=[recipient], subject=msg["Subject"], html=body, sender=sender)
                return
            except Exception:
                pass
        with smtplib.SMTP("smtp.gmail.com", 587) as smtp_server:
            smtp_server.starttls()
            smtp_server.login(sender or "unknown@example.com", password)
            smtp_server.sendmail(sender or "unknown@example.com", recipient, msg.as_string())

    @staticmethod
    def Send(
        subject=None,
        body=None,
        systemData=None,
        position=None,
        quantity=None,
        tradeTransactions=None,
        systemName=None,
        order=None,
    ):
        """
        Overloaded-like method for sending email in various usage patterns.
        """

        # 1) If subject & body were provided directly:
        if subject is not None and body is not None:
            GmailSMTP.sendEmail(subject, body)

        # 2) If (systemData, position, quantity) is used:
        if (
            systemData is not None
            and hasattr(Settings, "PositionSettings")
            and isinstance(position, getattr(Settings, "PositionSettings", tuple()))
            and quantity is not None
        ):
            description = getattr(position, "Description", "Unknown")
            position_type = getattr(position, "PositionType", "Unknown")
            symbol = getattr(position, "Symbol", "Unknown")
            order_type = getattr(position, "OrderType", None)
            limit_price = getattr(position, "LimitPrice", None)

            bodyNew = f"{systemData.get_datetime().date()} {description}"
            subjectNew = f"{position_type} {quantity} {symbol}"

            if hasattr(TypeEnums, "OrderType"):
                OrderType2: Any = getattr(TypeEnums, "OrderType", object())
                if order_type in (
                    getattr(OrderType2, "Limit", object()),
                    getattr(OrderType2, "LimitOnClose", object()),
                    getattr(OrderType2, "PeggedToMarket", object()),
                    getattr(OrderType2, "StopLimit", object()),
                    getattr(OrderType2, "Stop", object()),
                    getattr(OrderType2, "TrailingStop", object()),
                ):
                    subjectNew += f" @ {limit_price}"
                else:
                    subjectNew += " @ Market"
            else:
                subjectNew += " @ Market"

            GmailSMTP.sendEmail(subjectNew, bodyNew)

        # 3) If (systemData, tradeTransactions, systemName) is used:
        if systemData is not None and tradeTransactions is not None and systemName is not None:
            subjectNew = f"{systemName or ''} Transactions for {systemData.get_datetime().strftime('%m/%d/%Y')}"
            bodyNew = ""

            firstPosition = systemData.symbols_settings[0][0]
            indexTradeAction = (
                ZipUtil.parseIndexTradeAction(firstPosition) if ZipUtil is not None else "N/A"
            )

            bodyNew += f"Date: {systemData.get_datetime().strftime('%m/%d/%Y')}\n"
            bodyNew += f"IndexTradeAction: {indexTradeAction}\n"
            bodyNew += "---------------------------------------------------------\n"

            sortedTransacations = sorted(tradeTransactions, key=lambda x: (x.TradeType, x.Ticker))
            headerLength = len(bodyNew)

            for transaction in sortedTransacations:
                bodyNew += transaction.TradeType + " "

                if transaction.SizePercent is not None:
                    bodyNew += f"{transaction.SizePercent}%"
                else:
                    # find corresponding position object in systemData
                    pos = next(
                        (
                            x[0]
                            for sublist in systemData.symbols_settings.values()
                            for x in sublist
                            if x.symbol == transaction.Ticker
                        ),
                        None,
                    )
                    percent = "N/A"
                    if pos is not None:
                        percent = f"{(transaction.Size / pos.CurrentSize) * 100:.2f}"
                    bodyNew += f"{transaction.Size} shares ({percent} %)"

                bodyNew += f" {transaction.Ticker} @"
                bodyNew += (
                    transaction.OrderType
                    if str(transaction.OrderType) == "Market"
                    else str(transaction.Price)
                )
                bodyNew += f" - {transaction.Description}\n"

            if len(bodyNew) == headerLength:
                bodyNew += f"No transactions for {systemData.get_datetime().strftime('%m/%d/%Y')}\n"

            bodyNew += "---------------------------------------------------------\n"
            # This line below was unclear. If you want the count of open positions, you need len(...)
            open_positions_count = sum(
                len(pos_list) for pos_list in systemData.symbols_settings.values()
            )
            bodyNew += f"Open Positions : {open_positions_count}\n"

            for asset, positions in sorted(
                systemData.symbols_settings.items(), key=lambda x: x[0].symbol
            ):
                for pos in positions:
                    fraction_of_portfolio = (
                        pos.Size * pos.CostBasis / systemData.portfolio.portfolio_value
                    )
                    bodyNew += f"{pos.Type} {asset.Symbol} - entered at {fraction_of_portfolio:.2%} of portfolio"
                    bodyNew += f" since {pos.OpenDate.strftime('%Y-%m-%d')}"
                    # check if we are exiting
                    if any(
                        x.TradeType == "Exit" and x.PositionID == pos.ID for x in tradeTransactions
                    ):
                        bodyNew += " *** Exiting ***"
                    if pos.Description:
                        bodyNew += f" -- {pos.Description}"
                    bodyNew += "\n"

            GmailSMTP.sendEmail(subjectNew, bodyNew)

        # 4) If (systemData, order, quantity) is used:
        if (
            systemData is not None
            and hasattr(Settings, "OrderSettings")
            and isinstance(order, getattr(Settings, "OrderSettings", tuple()))
            and quantity is not None
        ):
            description = getattr(order, "Description", "Unknown")
            transaction_type = getattr(order, "TransactionType", "Unknown")
            symbol = getattr(order, "Symbol", "Unknown")
            order_type = getattr(order, "OrderType", None)
            limit_price = getattr(order, "LimitPrice", None)

            bodyNew = f"{systemData.CurrentDate} {description}"
            subjectNew = f"{transaction_type} {quantity} {symbol}"

            if hasattr(TypeEnums, "OrderType"):
                OrderType: Any = getattr(TypeEnums, "OrderType", object())
                if order_type in (
                    getattr(OrderType, "Limit", object()),
                    getattr(OrderType, "LimitOnClose", object()),
                    getattr(OrderType, "PeggedToMarket", object()),
                    getattr(OrderType, "StopLimit", object()),
                    getattr(OrderType, "Stop", object()),
                    getattr(OrderType, "TrailingStop", object()),
                ):
                    subjectNew += f" @ {limit_price}"
                else:
                    subjectNew += " @ Market"
            else:
                subjectNew += " @ Market"

            GmailSMTP.sendEmail(subjectNew, bodyNew)
