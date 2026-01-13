"""Streamlit-compatible logging utility for VEO API."""

import streamlit as st
from datetime import datetime
from typing import Optional


class StreamlitLogger:
    """Logger that outputs to Streamlit UI elements."""
    
    def __init__(self, container: Optional[st.delta_generator.DeltaGenerator] = None):
        """
        Initialize logger.
        
        Args:
            container: Streamlit container to write logs to
        """
        self.container = container
        self.logs = []
    
    def _format_message(self, level: str, message: str) -> str:
        """Format log message with timestamp and level."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        return f"[{timestamp}] {level}: {message}"
    
    def _write(self, level: str, message: str, emoji: str = ""):
        """Write log message."""
        formatted = self._format_message(level, message)
        self.logs.append(formatted)
        
        if self.container:
            display_msg = f"{emoji} {message}" if emoji else message
            
            if level == "ERROR":
                self.container.error(display_msg)
            elif level == "WARNING":
                self.container.warning(display_msg)
            elif level == "SUCCESS":
                self.container.success(display_msg)
            elif level == "INFO":
                self.container.info(display_msg)
            else:
                self.container.write(display_msg)
    
    def debug(self, message: str):
        """Log debug message."""
        self._write("DEBUG", message, "🔍")
    
    def info(self, message: str):
        """Log info message."""
        self._write("INFO", message, "ℹ️")
    
    def success(self, message: str):
        """Log success message."""
        self._write("SUCCESS", message, "✅")
    
    def warning(self, message: str):
        """Log warning message."""
        self._write("WARNING", message, "⚠️")
    
    def error(self, message: str):
        """Log error message."""
        self._write("ERROR", message, "❌")
    
    def get_logs(self) -> list:
        """Get all logged messages."""
        return self.logs
