# Regenerate video with modified template
from pixelle_video import pixelle_video
import asyncio

async def regenerate():
    await pixelle_video.initialize()

    result = await pixelle_video.pipelines["standard"](
        text="""当你面临收入不确定性时，现金流比什么都重要。越是收入不稳定，越要现金为王、保证流动性。
把一百万还进房子里，这笔钱就彻底锁死了。万一失业，你能从房子里把钱取出来吗？不能。
提前还贷的本质，是你在用今天的现金，重复购买同一套房子。如果房子没有投资价值，你买来干嘛？
房贷是普通人这辈子能拿到的最便宜的钱。利率低、期限长、不会被提前收回。主动放弃这个低成本杠杆，是最大的浪费。
富人和穷人的区别，不在于谁的负债更少，而在于谁更会利用杠杆。让每一分钱都为你工作，创造更大的价值。""",
        mode="fixed",
        title="千万不要提前还房贷",
        frame_template="1080x1920/image_default.html",
        tts_voice="zh-CN-YunjianNeural",
        tts_speed=1.1,
        split_mode="line"
    )

    print(f"Video generated: {result.video_path}")
    print(f"Duration: {result.duration}s")
    return result

# Run
if __name__ == "__main__":
    result = asyncio.run(regenerate())
