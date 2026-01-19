# -*- coding: utf-8 -*-
import re
import json
from lxml import etree
import log
from app.sites.siteuserinfo._base import _ISiteUserInfo, SITE_BASE_ORDER
from app.utils import StringUtils
from app.utils.types import SiteSchema


class FireFlySiteUserInfo(_ISiteUserInfo):
    schema = SiteSchema.FireFly
    order = SITE_BASE_ORDER + 3
    
    _level_map = {
        '1': '(新手)User',
        '2': '(入门)Power User',
        '3': '(发烧)Elite User',
        '4': '(着迷)Crazy User',
        '5': '(狂热)Insane User',
        '6': '(资深)Veteran User',
        '7': '(大师)Extreme User',
        '8': '(宗师)Ultimate User',
        '9': '(满级)Master User',
        '10': '(星级)Star User',
        '11': '(神级)God User'
    }

    @classmethod
    def match(cls, html_text):
        return 'Powered by FireFly' in html_text

    def _parse_site_page(self, html_text):
        html_text = self._prepare_html_text(html_text)
        user_detail = re.search(r"p_user/user_detail\.php\?uid=(\d+)", html_text)
        if user_detail:
            self.userid = user_detail.group(1)
            self._user_detail_page = f"p_user/user_detail.php?uid={self.userid}"
            self._torrent_seeding_page = f"p_torrent/torrent_user.php?pop=8&uid={self.userid}"
            self._user_mail_unread_page = "p_sms/msg_in.php"

    def _parse_message_unread(self, html_text):
        html = etree.HTML(html_text)
        if not html:
            return
        message_links = html.xpath('//a[contains(@href, "p_sms/msg_in.php")]/text()')
        if message_links:
            for msg_text in message_links:
                unread_match = re.search(r'(\d+)', msg_text)
                if unread_match:
                    self.message_unread = StringUtils.str_int(unread_match.group(1))
                    return

    def _parse_user_base_info(self, html_text):
        html = etree.HTML(html_text)
        if not html:
            return
        
        username_elements = html.xpath('//span[@class="uc1"]/text()')
        if username_elements:
            self.username = username_elements[0].strip()
        
        self._parse_user_traffic_info(html_text)
        self._parse_message_unread(html_text)

    def _parse_user_traffic_info(self, html_text):
        upload_match = re.search(r'上传\s*[：:]\s*([\d.,]+\s+[KMGTPI]+)', html_text, re.IGNORECASE)
        if upload_match:
            upload_str = upload_match.group(1).strip().replace(' ', '')
            if not upload_str.endswith('B'):
                upload_str += 'B'
            self.upload = StringUtils.num_filesize(upload_str)
        
        download_match = re.search(r'下载[：:]\s*([\d.,]+\s+[KMGTPI]+)', html_text, re.IGNORECASE)
        if download_match:
            download_str = download_match.group(1).strip().replace(' ', '')
            if not download_str.endswith('B'):
                download_str += 'B'
            self.download = StringUtils.num_filesize(download_str)
        
        if self.download > 0:
            self.ratio = round(self.upload / self.download, 3)
        else:
            self.ratio = 0.0
        
        bonus_match = re.search(r'魔力\s*[：:]\s*([\d,]+\.?\d*)', html_text)
        if bonus_match:
            self.bonus = StringUtils.str_float(bonus_match.group(1).replace(',', ''))

    def _parse_user_detail_info(self, html_text):
        html = etree.HTML(html_text)
        if not html:
            return
        
        rows = html.xpath('//tr[@id="tr_item"]')
        for row in rows:
            label_td = row.xpath('./td[@class="nowrap"]/text()')
            if not label_td:
                continue
            label = label_td[0].strip()
            
            if label == '加入日期':
                date_text = row.xpath('./td[2]/text()')
                if date_text:
                    self.join_at = StringUtils.unify_datetime_str(date_text[0].strip())
            
            elif label == '最近访问':
                date_text = row.xpath('./td[2]/text()')
                if date_text:
                    self.last_seen = StringUtils.unify_datetime_str(date_text[0].strip())
            
            elif label == '用户等级':
                img_elem = row.xpath('./td[2]/img/@src')
                if img_elem:
                    class_match = re.search(r'class(\d+)', img_elem[0])
                    if class_match:
                        class_num = class_match.group(1)
                        self.user_level = self._level_map.get(class_num, f"Class {class_num}")
            
            elif label == '传输':
                upload_td = row.xpath('.//tr[@id="tr_item_min"]/td[1]/text()')
                download_td = row.xpath('.//tr[@id="tr_item_min"]/td[3]/text()')
                if upload_td and upload_td[0].strip():
                    upload_str = upload_td[0].strip().replace(' ', '')
                    if not upload_str.endswith('B'):
                        upload_str += 'B'
                    self.upload = StringUtils.num_filesize(upload_str)
                if download_td and download_td[0].strip():
                    download_str = download_td[0].strip().replace(' ', '')
                    if not download_str.endswith('B'):
                        download_str += 'B'
                    self.download = StringUtils.num_filesize(download_str)
                
                ratio_td = row.xpath('.//tr[@id="tr_item_min"]/td[4]/text()')
                if ratio_td and ratio_td[0].strip() and ratio_td[0].strip() != '--':
                    self.ratio = StringUtils.str_float(ratio_td[0].strip())
                elif self.download > 0:
                    self.ratio = round(self.upload / self.download, 3)
            
            elif label == '魔力':
                bonus_text = row.xpath('./td[2]/text()')
                if bonus_text:
                    self.bonus = StringUtils.str_float(bonus_text[0].strip().replace(',', ''))

    def _parse_user_torrent_seeding_info(self, html_text, multi_page=False):
        html = etree.HTML(html_text)
        if not html:
            return None
        
        no_data = html.xpath('//td[contains(text(), "没有符合条件的种子")]')
        if no_data:
            return None
        
        torrent_rows = html.xpath('//table[@class="table_detail"]//tr[@id="tr_item" or @id="tr_list"]')
        if not torrent_rows:
            return None
        
        page_seeding_info = []
        for row in torrent_rows:
            size_td = row.xpath('.//td[contains(@class, "size") or position()=3]//text()')
            if size_td:
                size_text = ''.join(size_td).strip()
                size = StringUtils.num_filesize(size_text)
                if size > 0:
                    page_seeding_info.append([1, size])
        
        self.seeding += len(page_seeding_info)
        self.seeding_size += sum(info[1] for info in page_seeding_info)
        self.seeding_info.extend(page_seeding_info)
        
        return None

    def _parse_message_unread_links(self, html_text, msg_links):
        return None

    def _parse_message_content(self, html_text):
        return None, None, None
