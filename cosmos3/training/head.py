"""Small temporal/route waypoint decoder; deliberately has no backbone/label input."""

import torch
from torch import nn
from torch.nn import functional as F


class WaypointHead(nn.Module):
    def __init__(self, feature_dim=2048, width=128, visual_tokens=32, layers=2):
        super().__init__()
        self.config = dict(
            feature_dim=feature_dim,
            width=width,
            visual_tokens=visual_tokens,
            layers=layers,
        )
        self.visual = nn.Linear(feature_dim, width)
        self.visual_position = nn.Parameter(torch.randn(3, visual_tokens, width) * 0.01)
        self.history = nn.Linear(5, width)
        self.ego = nn.Linear(3, width)
        self.route = nn.Linear(2, width)
        self.route_position = nn.Parameter(torch.randn(32, width) * 0.01)
        self.queries = nn.Parameter(torch.randn(40, width) * 0.01)
        layer = nn.TransformerDecoderLayer(
            width, 4, width * 4, dropout=0, batch_first=True, norm_first=True
        )
        self.decoder = nn.TransformerDecoder(layer, layers, norm=nn.LayerNorm(width))
        self.output = nn.Linear(width, 3)
        self.register_buffer("future_s", torch.arange(1, 41).float() * 0.1)
        self.register_buffer("state_scale", torch.tensor([20.0, 20.0, 1.0]))

    def forward(
        self,
        features,
        ego_state,
        ego_history,
        history_mask,
        image_age_s,
        route,
        route_mask,
    ):
        batch, history, tokens, dim = features.shape
        if (history, tokens, dim) != (
            3,
            self.config["visual_tokens"],
            self.config["feature_dim"],
        ):
            raise ValueError("Feature shape differs from head contract")
        for value in (features, ego_state, ego_history, image_age_s, route):
            if not torch.isfinite(value).all():
                raise ValueError("Nonfinite policy input")
        if not history_mask[:, -1].all() or not route_mask.any(dim=1).all():
            raise ValueError("Current camera and navigation are required")
        visual = self.visual(features) + self.visual_position
        history_input = torch.cat(
            [
                ego_history / ego_history.new_tensor([20.0, 20.0, 1.0, 1.0]),
                image_age_s[..., None],
            ],
            dim=-1,
        )
        visual = visual + self.history(history_input)[:, :, None]
        memory = torch.cat(
            [
                visual.flatten(1, 2),
                self.ego(ego_state / self.state_scale)[:, None],
                self.route(route / 50.0) + self.route_position,
            ],
            dim=1,
        )
        mask = torch.cat(
            [
                ~history_mask[:, :, None].expand(-1, -1, tokens).flatten(1),
                torch.zeros((batch, 1), dtype=torch.bool, device=features.device),
                ~route_mask,
            ],
            dim=1,
        )
        decoded = self.decoder(
            self.queries[None].expand(batch, -1, -1),
            memory,
            memory_key_padding_mask=mask,
        )
        raw = self.output(decoded)
        # An explicit constant-velocity residual parameterization, not a fallback.
        xy = raw[..., :2] * 10.0 + ego_state[:, None, :2] * self.future_s[None, :, None]
        yaw = raw[..., 2] + ego_state[:, None, 2] * self.future_s
        return torch.cat([xy, yaw.sin()[..., None], yaw.cos()[..., None]], dim=-1)


def waypoint_loss(prediction, target, valid, ego_state):
    if (
        prediction.shape != target.shape
        or target.shape[1:] != (40, 4)
        or valid.shape != target.shape[:2]
    ):
        raise ValueError("Loss shape mismatch")
    if (
        not torch.isfinite(prediction).all()
        or not torch.isfinite(target).all()
        or not valid.any()
    ):
        raise ValueError("Invalid predictions/targets or empty supervision")
    xy = F.smooth_l1_loss(prediction[..., :2], target[..., :2], reduction="none").mean(
        -1
    )
    heading = 1 - (prediction[..., 2:] * target[..., 2:]).sum(-1)
    xy_loss, heading_loss = xy[valid].mean(), heading[valid].mean()
    first = valid[:, 0]
    speed_loss = (
        F.smooth_l1_loss(prediction[first, 0, :2] / 0.1, ego_state[first, :2])
        if first.any()
        else prediction.sum() * 0
    )
    loss = xy_loss + 0.2 * heading_loss + 0.01 * speed_loss
    return loss, {
        "xy_huber": float(xy_loss.detach()),
        "heading": float(heading_loss.detach()),
        "initial_velocity_huber": float(speed_loss.detach()),
    }
