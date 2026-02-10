import resend
from app.config import settings
from app.utils.logger import logger
from typing import Optional, Dict, Any
from jinja2 import Template


class EmailService:
    _initialized: bool = False
    
    @classmethod
    def _initialize(cls) -> bool:
        """Initialize Resend client"""
        if not settings.EMAIL_ENABLED:
            return False
        
        if not settings.RESEND_API_KEY:
            logger.warning("Resend API key not configured, email service disabled")
            return False
        
        if not cls._initialized:
            try:
                resend.api_key = settings.RESEND_API_KEY
                cls._initialized = True
                logger.info("Resend client initialized")
                return True
            except Exception as e:
                logger.error(f"Failed to initialize Resend client: {e}")
                return False
        
        return True
    
    @classmethod
    async def send_email(
        cls,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: Optional[str] = None,
        from_email: Optional[str] = None,
        from_name: Optional[str] = None
    ) -> bool:
        """Send an email via Resend"""
        if not settings.EMAIL_ENABLED:
            logger.debug("Email service disabled, skipping email send")
            return False
        
        if not cls._initialize():
            return False
        
        try:
            from_address = from_email or settings.EMAIL_FROM_ADDRESS
            from_name_str = from_name or settings.EMAIL_FROM_NAME
            
            # Format from address with name if provided
            if from_name_str and from_name_str != "Fullego":
                from_addr = f"{from_name_str} <{from_address}>"
            else:
                from_addr = from_address
            
            email_params = {
                "from": from_addr,
                "to": to_email,
                "subject": subject,
                "html": html_content,
            }
            
            # Add text content if provided
            if text_content:
                email_params["text"] = text_content
            
            # Run Resend send in thread to avoid blocking
            import asyncio
            response = await asyncio.to_thread(resend.Emails.send, email_params)
            
            if response and hasattr(response, 'id'):
                logger.info(f"Email sent successfully to {to_email} (ID: {response.id})")
                return True
            elif response:
                # Check if response is a dict with error
                if isinstance(response, dict) and 'error' in response:
                    logger.error(f"Failed to send email: {response.get('message', 'Unknown error')}")
                else:
                    logger.error(f"Failed to send email: Unexpected response format: {response}")
                return False
            else:
                logger.error(f"Failed to send email: No response received")
                return False
                
        except Exception as e:
            logger.error(f"Error sending email to {to_email}: {e}")
            return False
    
    @classmethod
    async def send_notification_email(
        cls,
        to_email: str,
        to_name: str,
        notification_title: str,
        notification_message: str,
        notification_type: str = "general"
    ) -> bool:
        """Send a notification email with formatted template"""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #4F46E5; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9fafb; padding: 30px; border-radius: 0 0 5px 5px; }
                .button { display: inline-block; padding: 12px 24px; background-color: #4F46E5; color: white; text-decoration: none; border-radius: 5px; margin-top: 20px; }
                .footer { text-align: center; margin-top: 20px; color: #6b7280; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Fullego</h1>
                </div>
                <div class="content">
                    <h2>{{ title }}</h2>
                    <p>Hi {{ name }},</p>
                    <p>{{ message }}</p>
                    <p>Best regards,<br>The Fullego Team</p>
                </div>
                <div class="footer">
                    <p>This is an automated notification from Fullego. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_template = """
        {{ title }}
        
        Hi {{ name }},
        
        {{ message }}
        
        Best regards,
        The Fullego Team
        
        ---
        This is an automated notification from Fullego. Please do not reply to this email.
        """
        
        try:
            html_content = Template(html_template).render(
                title=notification_title,
                name=to_name,
                message=notification_message
            )
            
            text_content = Template(text_template).render(
                title=notification_title,
                name=to_name,
                message=notification_message
            )
            
            return await cls.send_email(
                to_email=to_email,
                subject=notification_title,
                html_content=html_content,
                text_content=text_content
            )
        except Exception as e:
            logger.error(f"Error formatting notification email: {e}")
            return False
    
    @classmethod
    async def send_verification_email(
        cls,
        to_email: str,
        to_name: str,
        verification_token: str,
        verification_url: Optional[str] = None
    ) -> bool:
        """Send email verification email"""
        if not verification_url:
            verification_url = f"{settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else 'http://localhost:3000'}/verify-email?token={verification_token}"
        
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #4F46E5; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9fafb; padding: 30px; border-radius: 0 0 5px 5px; }
                .button { display: inline-block; padding: 12px 24px; background-color: #4F46E5; color: white; text-decoration: none; border-radius: 5px; margin-top: 20px; }
                .footer { text-align: center; margin-top: 20px; color: #6b7280; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Fullego</h1>
                </div>
                <div class="content">
                    <h2>Verify Your Email Address</h2>
                    <p>Hi {{ name }},</p>
                    <p>Thank you for signing up for Fullego! Please verify your email address by clicking the button below:</p>
                    <a href="{{ verification_url }}" class="button">Verify Email</a>
                    <p>Or copy and paste this link into your browser:</p>
                    <p style="word-break: break-all; color: #4F46E5;">{{ verification_url }}</p>
                    <p>This link will expire in 24 hours.</p>
                    <p>If you didn't create an account, please ignore this email.</p>
                </div>
                <div class="footer">
                    <p>This is an automated email from Fullego. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        try:
            html_content = Template(html_template).render(
                name=to_name,
                verification_url=verification_url
            )
            
            return await cls.send_email(
                to_email=to_email,
                subject="Verify Your Email Address - Fullego",
                html_content=html_content
            )
        except Exception as e:
            logger.error(f"Error sending verification email: {e}")
            return False
    
    @classmethod
    async def send_password_reset_email(
        cls,
        to_email: str,
        to_name: str,
        reset_token: str,
        reset_url: Optional[str] = None
    ) -> bool:
        """Send password reset email"""
        if not reset_url:
            reset_url = f"{settings.CORS_ORIGINS[0] if settings.CORS_ORIGINS else 'http://localhost:3000'}/reset-password?token={reset_token}"
        
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #4F46E5; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9fafb; padding: 30px; border-radius: 0 0 5px 5px; }
                .button { display: inline-block; padding: 12px 24px; background-color: #4F46E5; color: white; text-decoration: none; border-radius: 5px; margin-top: 20px; }
                .footer { text-align: center; margin-top: 20px; color: #6b7280; font-size: 12px; }
                .warning { background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; margin: 20px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Fullego</h1>
                </div>
                <div class="content">
                    <h2>Reset Your Password</h2>
                    <p>Hi {{ name }},</p>
                    <p>We received a request to reset your password. Click the button below to reset it:</p>
                    <a href="{{ reset_url }}" class="button">Reset Password</a>
                    <p>Or copy and paste this link into your browser:</p>
                    <p style="word-break: break-all; color: #4F46E5;">{{ reset_url }}</p>
                    <div class="warning">
                        <p><strong>Security Notice:</strong> This link will expire in 1 hour. If you didn't request a password reset, please ignore this email.</p>
                    </div>
                </div>
                <div class="footer">
                    <p>This is an automated email from Fullego. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        try:
            html_content = Template(html_template).render(
                name=to_name,
                reset_url=reset_url
            )
            
            return await cls.send_email(
                to_email=to_email,
                subject="Reset Your Password - Fullego",
                html_content=html_content
            )
        except Exception as e:
            logger.error(f"Error sending password reset email: {e}")
            return False
    
    @classmethod
    async def send_otp_email(
        cls,
        to_email: str,
        to_name: str,
        otp_code: str
    ) -> bool:
        """Send OTP verification email"""
        html_template = """
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; }
                .container { max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background-color: #4F46E5; color: white; padding: 20px; text-align: center; border-radius: 5px 5px 0 0; }
                .content { background-color: #f9fafb; padding: 30px; border-radius: 0 0 5px 5px; }
                .otp-box { background-color: #ffffff; border: 2px solid #4F46E5; border-radius: 8px; padding: 20px; text-align: center; margin: 20px 0; }
                .otp-code { font-size: 32px; font-weight: bold; color: #4F46E5; letter-spacing: 8px; font-family: 'Courier New', monospace; }
                .footer { text-align: center; margin-top: 20px; color: #6b7280; font-size: 12px; }
                .warning { background-color: #fef3c7; border-left: 4px solid #f59e0b; padding: 12px; margin: 20px 0; }
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Fullego</h1>
                </div>
                <div class="content">
                    <h2>Your Verification Code</h2>
                    <p>Hi {{ name }},</p>
                    <p>Your verification code is:</p>
                    <div class="otp-box">
                        <div class="otp-code">{{ otp_code }}</div>
                    </div>
                    <p>Enter this code to verify your email address.</p>
                    <div class="warning">
                        <p><strong>Security Notice:</strong> This code will expire in 10 minutes. Never share this code with anyone.</p>
                    </div>
                    <p>If you didn't request this code, please ignore this email.</p>
                </div>
                <div class="footer">
                    <p>This is an automated email from Fullego. Please do not reply to this email.</p>
                </div>
            </div>
        </body>
        </html>
        """
        
        text_template = """
        Your Verification Code - Fullego
        
        Hi {{ name }},
        
        Your verification code is: {{ otp_code }}
        
        Enter this code to verify your email address.
        
        Security Notice: This code will expire in 10 minutes. Never share this code with anyone.
        
        If you didn't request this code, please ignore this email.
        
        ---
        This is an automated email from Fullego. Please do not reply to this email.
        """
        
        try:
            html_content = Template(html_template).render(
                name=to_name,
                otp_code=otp_code
            )
            
            text_content = Template(text_template).render(
                name=to_name,
                otp_code=otp_code
            )
            
            return await cls.send_email(
                to_email=to_email,
                subject="Your Verification Code - Fullego",
                html_content=html_content,
                text_content=text_content
            )
        except Exception as e:
            logger.error(f"Error sending OTP email: {e}")
            return False
