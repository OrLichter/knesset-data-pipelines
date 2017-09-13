from datapackage_pipelines_knesset.common.processors.base_processor import BaseProcessor
from requests.exceptions import RequestException
import os, requests, logging, time, json


class DownloadCommitteeMeetingProtocolsProcessor(BaseProcessor):

    def __init__(self, *args, **kwargs):
        super(DownloadCommitteeMeetingProtocolsProcessor, self).__init__(*args, **kwargs)
        self._schema["fields"] = [
            {"name": "kns_committee_id", "type": "integer", "description": "primary key from kns_committee table"},
            {"name": "kns_session_id", "type": "integer", "description": "primary key from kns_committeesession table"},
            {"name": "protocol_file", "type": "string", "description": "relative path to the protocol file"},
            {"name": "protocol_url", "type": "string", "description": "full url to the downloaded protocol file"}
        ]
        self._schema["primaryKey"] = ["kns_session_id"]
        self._all_filenames = []

    def _process(self, datapackage, resources):
        return self._process_filter(datapackage, resources)

    def _reuqests_get(self, url):
        return requests.get(url)

    def _save_url_to_file(self, url, filename, num_retries, seconds_between_retries, retry_num=1):
        try:
            res = self._reuqests_get(url)
        except RequestException as e:
            if retry_num < num_retries:
                logging.exception(e)
                logging.info("retry {} / {}, waiting {} seconds before retrying...".format(retry_num, num_retries, seconds_between_retries))
                time.sleep(seconds_between_retries)
                return self._save_url_to_file(url, filename, num_retries, seconds_between_retries, retry_num+1)
            else:
                raise
        if res.status_code == 200:
            with open(filename, "wb") as f:
                f.write(res.content)
                return True
        else:
            return False

    def _get_filename(self, relpath):
        return os.path.join(self._parameters["out-path"], relpath)

    def _get_extension(self, meeting):
        ext = meeting["url"].strip()[-4:]
        if ext in [".doc", ".rtf"]:
            return ext[1:]
        else:
            logging.warning("unknown extension: {}".format(meeting["url"]))

    def _filter_row(self, meeting, **kwargs):
        if meeting["url"]:
            relpath = os.path.join(str(meeting["kns_committee_id"]), "{}.{}".format(meeting["kns_session_id"], self._get_extension(meeting)))
            filename = self._get_filename(relpath)
            if relpath not in self._all_filenames:
                os.makedirs(os.path.dirname(filename), exist_ok=True)
            override_meeting_ids = os.environ.get("OVERRIDE_COMMITTEE_MEETING_IDS")
            if not override_meeting_ids or str(meeting["kns_session_id"]) in override_meeting_ids.split(","):
                if not os.path.exists(filename):
                    override_meeting_ids = os.environ.get("OVERRIDE_COMMITTEE_MEETING_IDS")
                    if not override_meeting_ids or str(meeting["kns_session_id"]) in override_meeting_ids.split(","):
                        num_retries = self._parameters.get("num-retries", 5)
                        seconds_between_retries = self._parameters.get("seconds-between-retries", 60)
                        if self._save_url_to_file(meeting["url"], filename, num_retries, seconds_between_retries):
                            logging.info("downloaded {} -> {}".format(meeting["url"], filename))
                            self._all_filenames.append(relpath)
                        else:
                            filename = None
                if filename is not None:
                    yield {"kns_committee_id": meeting["kns_committee_id"],
                           "kns_session_id": meeting["kns_session_id"],
                           "protocol_file": filename,
                           "protocol_url": "https://next.oknesset.org/data/committee-meeting-protocols/{}".format(relpath)}

    def _process_cleanup(self):
        filename = self._get_filename("datapackage.json")
        with open(filename, "w") as f:
            descriptor = {"name": "_", "path": self._all_filenames}
            descriptor.update(**self._parameters.get("data-resource-descriptor", {}))
            json.dump({"name": "_", "resources": [descriptor]}, f)


if __name__ == '__main__':
    DownloadCommitteeMeetingProtocolsProcessor.main()
