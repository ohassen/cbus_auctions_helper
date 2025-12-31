"""HTML email report generation for auction matches."""

import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from jinja2 import Template

logger = logging.getLogger(__name__)


@dataclass
class EmailConfig:
    """Email configuration."""
    smtp_host: str
    smtp_port: int
    username: str
    password: str
    recipient: str
    sender: Optional[str] = None

    @classmethod
    def from_env(cls) -> "EmailConfig":
        """Load configuration from environment variables."""
        # Handle empty strings by using 'or' to fall back to defaults
        smtp_port_str = os.getenv("EMAIL_SMTP_PORT") or "587"
        return cls(
            smtp_host=os.getenv("EMAIL_SMTP_HOST") or "smtp.gmail.com",
            smtp_port=int(smtp_port_str),
            username=os.getenv("EMAIL_USER") or "",
            password=os.getenv("EMAIL_PASSWORD") or "",
            recipient=os.getenv("EMAIL_RECIPIENT") or "",
            sender=os.getenv("EMAIL_SENDER")
        )


EMAIL_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Auction Monitor Report</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 8px 8px 0 0;
            text-align: center;
        }
        .header h1 {
            margin: 0;
            font-size: 24px;
        }
        .header .date {
            opacity: 0.9;
            margin-top: 5px;
        }
        .summary {
            background: white;
            padding: 20px;
            border-left: 1px solid #ddd;
            border-right: 1px solid #ddd;
        }
        .summary-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-top: 10px;
        }
        .summary-item {
            background: #f8f9fa;
            padding: 15px;
            border-radius: 6px;
            text-align: center;
        }
        .summary-item .number {
            font-size: 28px;
            font-weight: bold;
            color: #667eea;
        }
        .summary-item .label {
            font-size: 12px;
            color: #666;
            text-transform: uppercase;
        }
        .items-container {
            background: white;
            border: 1px solid #ddd;
            border-top: none;
            border-radius: 0 0 8px 8px;
        }
        .item {
            padding: 20px;
            border-bottom: 1px solid #eee;
        }
        .item:last-child {
            border-bottom: none;
        }
        .item-header {
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            margin-bottom: 10px;
        }
        .item-title {
            font-size: 18px;
            font-weight: 600;
            color: #333;
            text-decoration: none;
            flex: 1;
        }
        .item-title:hover {
            color: #667eea;
        }
        .badge {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 4px;
            font-size: 11px;
            font-weight: 600;
            text-transform: uppercase;
            margin-left: 10px;
        }
        .badge-new {
            background: #28a745;
            color: white;
        }
        .badge-ending {
            background: #dc3545;
            color: white;
            animation: pulse 2s infinite;
        }
        .badge-discount {
            background: #ffc107;
            color: #333;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.7; }
        }
        .item-content {
            display: flex;
            gap: 15px;
        }
        .item-image {
            width: 120px;
            height: 120px;
            object-fit: cover;
            border-radius: 6px;
            background: #f0f0f0;
        }
        .item-details {
            flex: 1;
        }
        .price-row {
            display: flex;
            gap: 20px;
            margin-bottom: 8px;
        }
        .price {
            font-size: 20px;
            font-weight: bold;
            color: #28a745;
        }
        .msrp {
            color: #999;
            text-decoration: line-through;
        }
        .discount {
            color: #dc3545;
            font-weight: 600;
        }
        .meta-row {
            font-size: 13px;
            color: #666;
            margin: 5px 0;
        }
        .meta-row strong {
            color: #333;
        }
        .match-info {
            margin-top: 10px;
            padding: 10px;
            background: #f8f9fa;
            border-radius: 4px;
            font-size: 13px;
        }
        .match-score {
            display: inline-block;
            width: 40px;
            height: 40px;
            line-height: 40px;
            text-align: center;
            border-radius: 50%;
            font-weight: bold;
            color: white;
            margin-right: 10px;
        }
        .score-high { background: #28a745; }
        .score-medium { background: #ffc107; color: #333; }
        .score-low { background: #dc3545; }
        .footer {
            margin-top: 20px;
            padding: 15px;
            background: #f8f9fa;
            border-radius: 6px;
            font-size: 13px;
            color: #666;
            text-align: center;
        }
        .footer a {
            color: #667eea;
        }
        .no-items {
            padding: 40px;
            text-align: center;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>Auction Monitor Report</h1>
        <div class="date">{{ report_date }}</div>
    </div>

    <div class="summary">
        <h2 style="margin-top: 0;">Summary</h2>
        <div class="summary-grid">
            <div class="summary-item">
                <div class="number">{{ total_matches }}</div>
                <div class="label">Total Matches</div>
            </div>
            <div class="summary-item">
                <div class="number">{{ new_matches }}</div>
                <div class="label">New Today</div>
            </div>
            <div class="summary-item">
                <div class="number">{{ ending_soon }}</div>
                <div class="label">Ending Soon</div>
            </div>
            <div class="summary-item">
                <div class="number">{{ high_discount }}</div>
                <div class="label">&gt;70% Discount</div>
            </div>
        </div>
    </div>

    <div class="items-container">
        {% if items %}
            {% for item in items %}
            <div class="item">
                <div class="item-header">
                    <a href="{{ item.listing_url }}" class="item-title" target="_blank">
                        {{ item.title }}
                    </a>
                    {% if item.is_new %}
                        <span class="badge badge-new">New</span>
                    {% endif %}
                    {% if item.ending_soon %}
                        <span class="badge badge-ending">Ending Soon</span>
                    {% endif %}
                    {% if item.discount_pct and item.discount_pct >= 70 %}
                        <span class="badge badge-discount">{{ item.discount_pct|round|int }}% Off</span>
                    {% endif %}
                </div>

                <div class="item-content">
                    {% if item.image_urls and item.image_urls|length > 0 %}
                        <img src="{{ item.image_urls[0] }}" alt="{{ item.title }}" class="item-image">
                    {% else %}
                        <div class="item-image" style="display: flex; align-items: center; justify-content: center; color: #999;">
                            No Image
                        </div>
                    {% endif %}

                    <div class="item-details">
                        <div class="price-row">
                            <span class="price">${{ "%.2f"|format(item.current_price or 0) }}</span>
                            {% if item.msrp %}
                                <span class="msrp">${{ "%.2f"|format(item.msrp) }}</span>
                                <span class="discount">Save {{ item.discount_pct|round|int }}%</span>
                            {% endif %}
                        </div>

                        {% if item.condition %}
                            <div class="meta-row"><strong>Condition:</strong> {{ item.condition }}</div>
                        {% endif %}

                        {% if item.auction_end %}
                            <div class="meta-row"><strong>Ends:</strong> {{ item.auction_end_formatted }}</div>
                        {% endif %}

                        {% if item.pickup_location %}
                            <div class="meta-row"><strong>Pickup:</strong> {{ item.pickup_location }}</div>
                        {% endif %}

                        {% if item.pickup_dates %}
                            <div class="meta-row"><strong>Pickup Dates:</strong> {{ item.pickup_dates }}</div>
                        {% endif %}

                        <div class="meta-row"><strong>Source:</strong> {{ item.source_site }}</div>

                        {% if item.reasoning %}
                            <div class="match-info">
                                <span class="match-score {% if item.relevance_score >= 85 %}score-high{% elif item.relevance_score >= 70 %}score-medium{% else %}score-low{% endif %}">
                                    {{ item.relevance_score }}
                                </span>
                                {{ item.reasoning }}
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <div class="no-items">
                <h3>No matches found today</h3>
                <p>Your searches didn't find any new items matching your criteria.</p>
            </div>
        {% endif %}
    </div>

    <div class="footer">
        <p>
            This report was generated by the Auction Monitor CLI tool.<br>
            To modify your searches, edit the <code>searches.json</code> file in your repository.
        </p>
        <p>
            <a href="https://github.com/your-repo/auction-monitor">View on GitHub</a>
        </p>
    </div>
</body>
</html>
"""


def generate_report_html(items: list[dict], report_date: Optional[datetime] = None) -> str:
    """Generate HTML report from matched items."""

    if report_date is None:
        report_date = datetime.now()

    # Calculate summary stats
    total_matches = len(items)
    new_matches = sum(1 for item in items if item.get("is_new"))
    ending_soon = 0
    high_discount = 0

    # Process items for display
    processed_items = []
    now = datetime.now()
    soon_threshold = now + timedelta(hours=48)

    for item in items:
        processed = dict(item)

        # Check if ending soon
        auction_end = item.get("auction_end")
        if auction_end:
            if isinstance(auction_end, str):
                try:
                    auction_end = datetime.fromisoformat(auction_end)
                except ValueError:
                    auction_end = None

            if auction_end and auction_end <= soon_threshold:
                processed["ending_soon"] = True
                ending_soon += 1
            else:
                processed["ending_soon"] = False

            # Format for display
            if auction_end:
                processed["auction_end_formatted"] = auction_end.strftime("%B %d, %Y at %I:%M %p")
        else:
            processed["ending_soon"] = False

        # Check high discount
        if item.get("discount_pct") and item["discount_pct"] >= 70:
            high_discount += 1

        processed_items.append(processed)

    # Sort by relevance score descending
    processed_items.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)

    # Render template
    template = Template(EMAIL_TEMPLATE)
    html = template.render(
        report_date=report_date.strftime("%B %d, %Y"),
        items=processed_items,
        total_matches=total_matches,
        new_matches=new_matches,
        ending_soon=ending_soon,
        high_discount=high_discount
    )

    return html


def send_email_report(
    config: EmailConfig,
    html_content: str,
    subject: Optional[str] = None,
    match_count: int = 0
) -> bool:
    """Send the email report via SMTP."""

    if not config.username or not config.password:
        logger.error("Email credentials not configured")
        return False

    if not config.recipient:
        logger.error("Email recipient not configured")
        return False

    if subject is None:
        date_str = datetime.now().strftime("%Y-%m-%d")
        subject = f"Auction Monitor - {date_str} - {match_count} Match{'es' if match_count != 1 else ''} Found"

    sender = config.sender or config.username

    # Create message
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = config.recipient

    # Plain text version (simple fallback)
    text_content = f"""
Auction Monitor Report

Found {match_count} matching items today.

Please view this email in an HTML-capable email client to see the full report.

To modify your searches, edit the searches.json file in your repository.
"""

    msg.attach(MIMEText(text_content, "plain"))
    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(config.smtp_host, config.smtp_port) as server:
            server.starttls()
            server.login(config.username, config.password)
            server.sendmail(sender, config.recipient, msg.as_string())

        logger.info(f"Email sent successfully to {config.recipient}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP authentication failed: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error: {e}")
        return False
    except Exception as e:
        logger.error(f"Failed to send email: {e}")
        return False


def send_error_report(config: EmailConfig, error_message: str, site_name: str) -> bool:
    """Send an error notification email."""

    subject = f"Auction Monitor - Error with {site_name}"

    html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: sans-serif; padding: 20px; }}
        .error-box {{
            background: #fee;
            border: 1px solid #c00;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
        }}
        .error-box h2 {{ color: #c00; margin-top: 0; }}
    </style>
</head>
<body>
    <h1>Auction Monitor Error Report</h1>

    <div class="error-box">
        <h2>Error Encountered</h2>
        <p><strong>Site:</strong> {site_name}</p>
        <p><strong>Error:</strong></p>
        <pre>{error_message}</pre>
    </div>

    <p>The auction monitor encountered an error while processing. Other sites may have been processed successfully.</p>
    <p>Please check the logs for more details.</p>
</body>
</html>
"""

    return send_email_report(config, html_content, subject=subject)
