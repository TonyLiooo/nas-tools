import json
import re
import httpx
import openai
from openai import OpenAI

from app.utils import OpenAISessionCache
from app.utils.commons import singleton
from config import Config

api_model_map = {
    "sk-": "gpt-4o-mini",                   # OpenAI
    "googleapis.com": "gemini-1.5-flash",   # Gemini
    "xai-": "grok-beta",                    # xAI
    "xf-yun.com": "lite",                   # 讯飞
    "cloudflare.com": "@cf/meta/llama-3.2-3b-instruct"  # Cloudflare
}

@singleton
class OpenAiHelper:
    _api_key = None
    _api_url = None
    _api_model = None
    _proxy = None

    def __init__(self):
        self.init_config()

    def init_config(self):
        self._api_key = Config().get_config("openai").get("api_key")
        self._api_url = Config().get_config("openai").get("api_url")
        self._api_model = Config().get_config("openai").get("api_model")
        self._proxy = Config().get_proxies()
        if not self._api_key:
            return
        if not self._api_model:
            self._api_model = next(
                (model for key, model in api_model_map.items()
                    if (self._api_url and key in self._api_url) or (self._api_key and self._api_key.startswith(key))),
                "gpt-4o-mini"
            )
        if self._api_url and not re.search(r"/v\d+", self._api_url):
            self._api_url += "/v1"
        proxies : dict = {}
        proxy = self._proxy.get("http", None)
        if proxy:
            if proxy.startswith("http"):
                proxies["http://"] = proxy
            elif "://" not in proxy:
                proxies["http://"] = "http://" + proxy
        proxy = self._proxy.get("https", None)
        if proxy:
            if proxy.startswith("http"):
                proxies["https://"] = proxy
            elif "://" not in proxy:
                proxies["https://"] = "https://" + proxy

        self._client = OpenAI(
            base_url=self._api_url,
            api_key=self._api_key,
            http_client=httpx.Client(proxies=proxies)
        )

    def get_state(self):
        return True if self._api_key else False

    @staticmethod
    def __save_session(session_id, message):
        """
        保存会话
        :param session_id: 会话ID
        :param message: 消息
        :return:
        """
        seasion = OpenAISessionCache.get(session_id)
        if seasion:
            seasion.append({
                "role": "assistant",
                "content": message
            })
            OpenAISessionCache.set(session_id, seasion)

    @staticmethod
    def __get_session(session_id, message):
        """
        获取会话
        :param session_id: 会话ID
        :return: 会话上下文
        """
        seasion = OpenAISessionCache.get(session_id)
        if seasion:
            seasion.append({
                "role": "user",
                "content": message
            })
        else:
            seasion = [
                {
                    "role": "system",
                    "content": "请在接下来的对话中请使用中文回复，并且内容尽可能详细。"
                },
                {
                    "role": "user",
                    "content": message
                }]
            OpenAISessionCache.set(session_id, seasion)
        return seasion

    def __get_model(self,
                    message,
                    prompt=None,
                    user="NAStool",
                    **kwargs):
        """
        获取模型
        """
        if not isinstance(message, list):
            if prompt:
                message = [
                    {
                        "role": "system",
                        "content": prompt
                    },
                    {
                        "role": "user",
                        "content": message
                    }
                ]
            else:
                message = [
                    {
                        "role": "user",
                        "content": message
                    }
                ]
        if "gemini" in self._api_model:
            return self._client.chat.completions.create(
                model=self._api_model,
                messages=message,
                **kwargs
            )
        else:
            return self._client.chat.completions.create(
                model=self._api_model,
                user=user,
                messages=message,
                **kwargs
            )

    @staticmethod
    def __clear_session(session_id):
        """
        清除会话
        :param session_id: 会话ID
        :return:
        """
        if OpenAISessionCache.get(session_id):
            OpenAISessionCache.delete(session_id)

    def get_media_name(self, filename):
        """
        从文件名中提取媒体名称等要素
        :param filename: 文件名
        :return: Json
        """
        if not self.get_state():
            return None
        result = ""
        try:
            _filename_prompt = "I will give you a movie/tvshow file name.You need to return a Json." \
                               "\nPay attention to the correct identification of the film name." \
                               "\n{\"title\":string,\"version\":string,\"part\":string,\"year\":string,\"resolution\":string,\"season\":number|null,\"episode\":number|null}"
            completion = self.__get_model(prompt=_filename_prompt, message=filename)
            result = completion.choices[0].message.content
            return json.loads(result)
        except Exception as e:
            print(f"{str(e)}：{result}")
            return {}

    def get_answer(self, text, userid):
        """
        获取答案
        :param text: 输入文本
        :param userid: 用户ID
        :return:
        """
        if not self.get_state():
            return ""
        try:
            if not userid:
                return "用户信息错误"
            else:
                userid = str(userid)
            if text == "#清除":
                self.__clear_session(userid)
                return "会话已清除"
            # 获取历史上下文
            messages = self.__get_session(userid, text)
            completion = self.__get_model(message=messages, user=userid)
            result = completion.choices[0].message.content
            if result:
                self.__save_session(userid, text)
            return result
        except openai.RateLimitError as e:
            return f"请求被ChatGPT拒绝了，{str(e)}"
        except openai.APIConnectionError as e:
            return "ChatGPT网络连接失败！"
        except openai.APITimeoutError as e:
            return "没有接收到ChatGPT的返回消息！"
        except Exception as e:
            return f"请求ChatGPT出现错误：{str(e)}"

    def translate_to_zh(self, text):
        """
        翻译为中文
        :param text: 输入文本
        """
        if not self.get_state():
            return False, None
        system_prompt = "You are a translation engine that can only translate text and cannot interpret it."
        user_prompt = f"translate to zh-CN:\n\n{text}"
        result = ""
        try:
            completion = self.__get_model(prompt=system_prompt,
                                          message=user_prompt,
                                          temperature=0,
                                          top_p=1,
                                          frequency_penalty=0,
                                          presence_penalty=0)
            result = completion.choices[0].message.content.strip()
            return True, result
        except Exception as e:
            print(f"{str(e)}：{result}")
            return False, str(e)

    def get_question_answer(self, question):
        """
        从给定问题和选项中获取正确答案
        :param question: 问题及选项
        :return: Json
        """
        if not self.get_state():
            return None
        result = ""
        try:
            _question_prompt = "下面我们来玩一个游戏，你是老师，我是学生，你需要回答我的问题，我会给你一个题目和几个选项，你的回复必须是给定选项中正确答案对应的序号，请直接回复数字"
            completion = self.__get_model(prompt=_question_prompt, message=question)
            result = completion.choices[0].message.content
            return result
        except Exception as e:
            print(f"{str(e)}：{result}")
            return {}
