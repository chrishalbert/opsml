from typing import Any, Dict, List, Optional, Union, cast, Tuple

from pydantic import BaseModel, root_validator

from opsml.helpers.logging import ArtifactLogger
from opsml.helpers.utils import experimental_feature
from opsml.registry.cards.cards import ModelCard, RunCard
from opsml.registry.cards.types import CardInfo, Metric
from opsml.registry.sql.registry import CardRegistries

logger = ArtifactLogger.get_logger(__name__)

# User interfaces should primarily be checked at runtime


class BattleReport(BaseModel):
    champion_name: str
    champion_version: str
    champion_metric: Optional[Metric] = None
    challenger_metric: Optional[Metric] = None
    challenger_win: bool

    class Config:
        arbitrary_types_allowed = True


MetricName = Union[str, List[str]]
MetricValue = Union[int, float, List[Union[int, float]]]


class ChallengeInputs(BaseModel):
    metric_name: MetricName
    metric_value: Optional[MetricValue] = None
    lower_is_better: Union[bool, List[bool]] = True

    class Config:
        underscore_attrs_are_private = True

    @root_validator(pre=False)
    def convert_to_list(cls, values):
        metric_name = values["metric_name"]
        metric_value = values["metric_value"]
        lower_is_better = values["lower_is_better"]

        if not isinstance(metric_name, list):
            values["metric_name"] = [metric_name]

        if not isinstance(lower_is_better, list):
            values["lower_is_better"] = [lower_is_better] * len(values["metric_name"])

        if metric_value is not None:
            if not isinstance(metric_value, list):
                values["metric_value"] = [metric_value]
        else:
            values["metric_value"] = [None] * len(values["metric_name"])

        if not all(
            len(values["metric_name"]) == len(list_)
            for list_ in [
                values["metric_name"],
                values["metric_value"],
                values["lower_is_better"],
            ]
        ):
            raise ValueError("Metric name, value and lower_is_better should all match in length")

        return values


class ModelChallenger:
    @experimental_feature
    def __init__(self, challenger: ModelCard):
        """
        Instantiates ModelChallenger class

        Args:
            challenger:
                ModelCard of challenger

        """
        self._challenger = challenger
        self._challenger_metric: Optional[Metric] = None
        self._registries = CardRegistries()

    @property
    def challenger_metric(self) -> Metric:
        if self._challenger_metric is not None:
            return self._challenger_metric
        raise ValueError("Challenger metric not set")

    @challenger_metric.setter
    def challenger_metric(self, metric: Metric):
        self._challenger_metric = metric

    def _get_last_champion_record(self) -> Optional[Dict[str, Any]]:
        """Gets the previous champion record"""

        champion_records = self._registries.model.list_cards(
            name=self._challenger.name,
            team=self._challenger.team,
            as_dataframe=False,
        )

        if not bool(champion_records):
            return None

        # indicates challenger has been registered
        if self._challenger.version is not None and len(champion_records) > 1:
            return champion_records[1]

        # account for cases where challenger is only model in registry
        champion_record = champion_records[0]
        if champion_record.get("version") == self._challenger.version:
            return None

        return champion_record

    def _get_runcard_metric(self, runcard_uid: str, metric_name: str) -> Metric:
        """
        Loads a RunCard from uid

        Args:
            runcard_uid:
                RunCard uid
            metric_name:
                Name of metric

        """
        runcard: RunCard = self._registries.run.load_card(uid=runcard_uid)

        return cast(Metric, runcard.get_metric(name=metric_name))

    def _battle(self, champion: CardInfo, champion_metric: Metric, lower_is_better: bool) -> BattleReport:
        """
        Runs a battle between champion and current challenger

        Args:
            champion:
                Champion record
            champion_metric:
                Champion metric from a runcard
            lower_is_better:
                Whether lower metric is preferred

        Returns:
            `BattleReport`

        """

        if lower_is_better:
            challenger_win = self.challenger_metric.value < champion_metric.value
        else:
            challenger_win = self.challenger_metric.value > champion_metric.value

        return BattleReport.construct(
            champion_name=str(champion.name),
            champion_version=str(champion.version),
            champion_metric=champion_metric,
            challenger_metric=self.challenger_metric.copy(),
            challenger_win=challenger_win,
        )

    def _battle_last_model_version(self, metric_name: str, lower_is_better: bool) -> BattleReport:
        """Compares the last champion model to the current challenger"""

        champion_record = self._get_last_champion_record()

        if champion_record is None:
            logger.info("No previous model found. Challenger wins")

            return BattleReport(
                champion_name="No model",
                champion_version="No version",
                challenger_win=True,
            )

        runcard_id = champion_record.get("runcard_uid")
        if runcard_id is None:
            raise ValueError(f"No RunCard is associated with champion: {champion_record}")

        champion_metric = self._get_runcard_metric(runcard_uid=runcard_id, metric_name=metric_name)

        return self._battle(
            champion=CardInfo(
                name=champion_record.get("name"),
                version=champion_record.get("version"),
            ),
            champion_metric=champion_metric,
            lower_is_better=lower_is_better,
        )

    def _battle_champions(
        self,
        champions: List[CardInfo],
        metric_name: str,
        lower_is_better: bool,
    ) -> List[BattleReport]:
        """Loops through and creates a `BattleReport` for each champion"""
        battle_reports = []
        for champion in champions:
            champion_record = self._registries.model.list_cards(info=champion, as_dataframe=False)

            if not bool(champion_record):
                raise ValueError(f"Champion model does not exist. {champion}")

            champion_card = champion_record[0]
            if champion_card.get("runcard_uid") is None:
                raise ValueError(f"No RunCard associated with champion: {champion}")

            champion_metric = self._get_runcard_metric(
                runcard_uid=champion_card.get("runcard_uid"),
                metric_name=metric_name,
            )

            # update name, team and version in case of None
            champion.name = champion.name or champion_card.get("name")
            champion.team = champion.team or champion_card.get("team")
            champion.version = champion.version or champion_card.get("version")

            battle_reports.append(
                self._battle(
                    champion=champion,
                    champion_metric=champion_metric,
                    lower_is_better=lower_is_better,
                )
            )
        return battle_reports

    def challenge_champion(
        self,
        metric_name: MetricName,
        metric_value: Optional[MetricValue] = None,
        champions: Optional[List[CardInfo]] = None,
        lower_is_better: Union[bool, List[bool]] = True,
    ) -> Dict[str, List[BattleReport]]:
        """
        Challenges n champion models against the challenger model. If no champion is provided,
        the latest model version is used as a champion.

        Args:
            champions:
                Optional list of champion CardInfo
            metric_name:
                Name of metric to evaluate
            metric_value:
                Challenger metric value
            lower_is_better:
                Whether a lower metric value is better or not

        Returns
            `BattleReport`
        """

        # validate inputs
        inputs = ChallengeInputs(
            metric_name=metric_name,
            metric_value=metric_value,
            lower_is_better=lower_is_better,
        )

        report_dict = {}
        for name, value, _lower_is_better in zip(
            inputs.metric_name,
            inputs.metric_value,
            inputs.lower_is_better,
        ):
            # get challenger metric
            if value is None:
                if self._challenger.runcard_uid is not None:
                    self.challenger_metric = self._get_runcard_metric(self._challenger.runcard_uid, metric_name=name)
                else:
                    raise ValueError("Challenger and champions must be associated with a registered RunCard")
            else:
                self.challenger_metric = Metric(name=name, value=value)

            if champions is None:
                report_dict[name] = [
                    self._battle_last_model_version(
                        metric_name=name,
                        lower_is_better=_lower_is_better,
                    )
                ]

            else:
                report_dict[name] = self._battle_champions(
                    champions=champions,
                    metric_name=name,
                    lower_is_better=_lower_is_better,
                )

        return report_dict
