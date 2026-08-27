"""Local LiveKit console entrypoint for Step-1 voice mode."""

from livekit.agents import AgentServer, JobContext, cli

from jarvis.config import JarvisConfig
from jarvis.logging_config import configure_logging
from jarvis.voice.agent import JarvisVoiceAgent
from jarvis.voice.livekit_session import create_voice_session

server = AgentServer()


@server.rtc_session()
async def voice_session(ctx: JobContext) -> None:
    config = JarvisConfig.from_environment()
    configure_logging(config.log_level)
    session, bridge = create_voice_session(config)
    bridge.conversation.start()
    try:
        await session.start(room=ctx.room, agent=JarvisVoiceAgent())
        await ctx.connect()
    except BaseException:
        bridge.conversation.fail()
        raise


if __name__ == "__main__":
    cli.run_app(server)
