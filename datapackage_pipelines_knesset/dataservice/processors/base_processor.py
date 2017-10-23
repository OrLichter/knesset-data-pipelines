from datapackage_pipelines_knesset.common.processors.base_processor import BaseProcessor
from knesset_data.dataservice.base import KnessetDataServiceSimpleField
from datapackage_pipelines_knesset.dataservice.exceptions import InvalidStatusCodeException, ReachedMaxRetries
import datetime, requests, logging, time, os


def is_blocked(content):
    for str in ['if(u82222.w(u82222.O', 'window.rbzid=', '<html><head><meta charset="utf-8"><script>']:
        if str in content:
            return True
    return False


def get_retry_response_content(url, params, timeout, proxies, retry_num, num_retries, seconds_between_retries):
    proxies = proxies if proxies else {}
    if os.environ.get("DATASERVICE_HTTP_PROXY"):
        proxies["http"] = os.environ["DATASERVICE_HTTP_PROXY"]
    try:
        response = requests.get(url, params=params, timeout=timeout, proxies=proxies)
    except requests.exceptions.InvalidSchema:
        # missing dependencies for SOCKS support
        raise
    except requests.RequestException as e:
        # network / http problem - start the retry mechanism
        if (retry_num < num_retries):
            logging.exception(e)
            logging.info("retry {} / {}, waiting {} seconds before retrying...".format(retry_num,
                                                                                       num_retries,
                                                                                       seconds_between_retries))
            time.sleep(seconds_between_retries)
            return get_retry_response_content(url, params, timeout, proxies, retry_num + 1, num_retries, seconds_between_retries)
        else:
            raise ReachedMaxRetries(e)
    if response.status_code != 200:
        # http status_code is not 200 - retry won't help here
        raise InvalidStatusCodeException(response.status_code, response.content)
    elif is_blocked(response.text):
        logging.info(response.text)
        raise Exception("seems your request is blocked, you should use the app ssh socks proxy\n"
                        "url={}\n"
                        "params={}\n"
                        "proxies={}".format(url, params, proxies))
    else:
        return response.content


class BaseDataserviceProcessor(BaseProcessor):

    def __init__(self, *args, **kwargs):
        super(BaseDataserviceProcessor, self).__init__(*args, **kwargs)
        fields = []
        self._primary_key_field_name = "id"
        class DataServiceClass(self._get_base_dataservice_class()):
            ORDERED_FIELDS = []
            for name, field in self._parameters["fields"].items():
                field_source = field.pop("source", None)
                if field.pop("primaryKey", False):
                    self._primary_key_field_name = name
                field["name"] = name
                # dump.to_path forces these formats for dates
                if field["type"] == "datetime":
                    field["format"] = "fmt:%Y-%m-%d %H:%M:%S.%f"
                elif field["type"] == "date":
                    field["format"] = "fmt:%Y-%m-%d"
                fields.append(field)
                if field_source:
                    field_source = field_source.format(name=name)
                    ORDERED_FIELDS.append((name, KnessetDataServiceSimpleField(field_source, field["type"])))
        self._schema = {"fields": fields,
                       "primaryKey": [self._primary_key_field_name]}
        self.dataservice_class = self._extend_dataservice_class(DataServiceClass)

    def _get_base_dataservice_class(self):
        raise NotImplementedError()

    def _extend_dataservice_class(self, dataservice_class):
        num_retries = self._parameters.get("num-retries", 10)
        seconds_between_retries = self._parameters.get("seconds-between-retries", 60)
        class BaseExtendedDataserviceClass(dataservice_class):
            @classmethod
            def _get_response_content(cls, url, params, timeout, proxies, retry_num=1):
                return get_retry_response_content(url, params, timeout, proxies, retry_num, num_retries, seconds_between_retries)
        return BaseExtendedDataserviceClass

    def _filter_output_row(self, row):
        for field in self._schema["fields"]:
            value = row.get(field["name"], None)
            row[field["name"]] = value
        return row

    def _get_dataservice_objects(self, *args, **kwargs):
        raise NotImplementedError()

    def _filter_dataservice_object(self, dataservice_object):
        return self._filter_output_row(dataservice_object.all_field_values())
