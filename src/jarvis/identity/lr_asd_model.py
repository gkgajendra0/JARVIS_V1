"""Minimal LR-ASD inference network adapted for JARVIS.

Architecture adapted from Junhua-Liao/LR-ASD at commit
1b6dcd2d8fc2895683de6508ec6294ec47d388ca under the MIT license.
Only the model needed for in-memory inference is retained; the upstream demo,
training loop, face detector, file conversion, and hard-coded CUDA wrapper are
intentionally excluded.
"""

from __future__ import annotations

import torch
from torch import nn


class _AudioBlock(nn.Module):
    def __init__(self, in_channels: int, out_channels: int, kernel_1: int, kernel_2: int):
        super().__init__()
        p1 = (kernel_1 - 1) // 2
        p2 = (kernel_2 - 1) // 2
        self.relu = nn.ReLU()
        self.m_1 = nn.Conv2d(
            in_channels,
            out_channels // 2,
            kernel_size=(kernel_1, 1),
            padding=(p1, 0),
            bias=False,
        )
        self.m_norm_1 = nn.BatchNorm2d(out_channels // 2, momentum=0.01, eps=0.001)
        self.m_2 = nn.Conv2d(
            out_channels // 2,
            out_channels,
            kernel_size=(kernel_2, 1),
            padding=(p2, 0),
            bias=False,
        )
        self.m_norm_2 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.t_1 = nn.Conv2d(
            out_channels,
            out_channels,
            kernel_size=(1, kernel_1),
            padding=(0, p1),
            bias=False,
        )
        self.t_norm_1 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)
        self.t_2 = nn.Conv2d(
            out_channels,
            out_channels,
            kernel_size=(1, kernel_2),
            padding=(0, p2),
            bias=False,
        )
        self.t_norm_2 = nn.BatchNorm2d(out_channels, momentum=0.01, eps=0.001)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.relu(self.m_norm_1(self.m_1(x)))
        x = self.relu(self.m_norm_2(self.m_2(x)))
        x = self.relu(self.t_norm_1(self.t_1(x)))
        return self.relu(self.t_norm_2(self.t_2(x)))


class _VisualBlock(nn.Module):
    def __init__(
        self,
        in_channels: int,
        out_channels: int,
        kernel_1: int,
        kernel_2: int,
        *,
        is_down: bool = False,
    ) -> None:
        super().__init__()
        p1 = (kernel_1 - 1) // 2
        p2 = (kernel_2 - 1) // 2
        stride = (1, 2, 2) if is_down else (1, 1, 1)
        self.relu = nn.ReLU()
        self.s_1 = nn.Conv3d(
            in_channels,
            out_channels // 2,
            kernel_size=(1, kernel_1, kernel_1),
            stride=stride,
            padding=(0, p1, p1),
            bias=False,
        )
        self.s_norm_1 = nn.BatchNorm3d(out_channels // 2, momentum=0.01, eps=0.001)
        self.s_2 = nn.Conv3d(
            out_channels // 2,
            out_channels,
            kernel_size=(1, kernel_2, kernel_2),
            padding=(0, p2, p2),
            bias=False,
        )
        self.s_norm_2 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.t_1 = nn.Conv3d(
            out_channels,
            out_channels,
            kernel_size=(kernel_1, 1, 1),
            padding=(p1, 0, 0),
            bias=False,
        )
        self.t_norm_1 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)
        self.t_2 = nn.Conv3d(
            out_channels,
            out_channels,
            kernel_size=(kernel_2, 1, 1),
            padding=(p2, 0, 0),
            bias=False,
        )
        self.t_norm_2 = nn.BatchNorm3d(out_channels, momentum=0.01, eps=0.001)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.relu(self.s_norm_1(self.s_1(x)))
        x = self.relu(self.s_norm_2(self.s_2(x)))
        x = self.relu(self.t_norm_1(self.t_1(x)))
        return self.relu(self.t_norm_2(self.t_2(x)))


class _VisualEncoder(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.block1 = _VisualBlock(1, 32, 5, 3, is_down=True)
        self.pool1 = nn.MaxPool3d(
            kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1)
        )
        self.block2 = _VisualBlock(32, 64, 5, 3)
        self.pool2 = nn.MaxPool3d(
            kernel_size=(1, 3, 3), stride=(1, 2, 2), padding=(0, 1, 1)
        )
        self.block3 = _VisualBlock(64, 128, 5, 3)
        self.maxpool = nn.AdaptiveMaxPool2d((1, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.pool1(self.block1(x))
        x = self.pool2(self.block2(x))
        x = self.block3(x).transpose(1, 2)
        batch, frames, channels, width, height = x.shape
        x = x.reshape(batch * frames, channels, width, height)
        x = self.maxpool(x)
        return x.view(batch, frames, channels)


class _AudioEncoder(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.block1 = _AudioBlock(1, 32, 5, 3)
        self.pool1 = nn.MaxPool3d(
            kernel_size=(1, 1, 3), stride=(1, 1, 2), padding=(0, 0, 1)
        )
        self.block2 = _AudioBlock(32, 64, 5, 3)
        self.pool2 = nn.MaxPool3d(
            kernel_size=(1, 1, 3), stride=(1, 1, 2), padding=(0, 0, 1)
        )
        self.block3 = _AudioBlock(64, 128, 5, 3)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = self.pool1(self.block1(x))
        x = self.pool2(self.block2(x))
        x = self.block3(x)
        x = torch.mean(x, dim=2, keepdim=True)
        return x.squeeze(2).transpose(1, 2)


class _Fusion(nn.Module):
    def __init__(self, channel: int) -> None:
        super().__init__()
        self.sigmoid = nn.Sigmoid()
        self.attention = nn.Conv1d(channel, channel, kernel_size=1, bias=False)
        self.bn = nn.BatchNorm1d(channel, momentum=0.01, eps=0.001)

    def forward(self, x1: torch.Tensor, x2: torch.Tensor) -> torch.Tensor:
        x = torch.cat((x1, x2), dim=2)
        identity = x.transpose(1, 2)
        weight = self.sigmoid(self.bn(self.attention(identity)))
        return (identity * weight).transpose(1, 2)


class _Detector(nn.Module):
    def __init__(self, channel: int) -> None:
        super().__init__()
        self.gru_forward = nn.GRU(
            input_size=channel,
            hidden_size=channel // 4,
            num_layers=1,
            batch_first=True,
        )
        self.gru_backward = nn.GRU(
            input_size=channel,
            hidden_size=channel // 4,
            num_layers=1,
            batch_first=True,
        )
        self.drop = nn.Dropout(0.5)
        self.attention = _Fusion(channel // 2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x1, _ = self.gru_forward(self.drop(x))
        backward, _ = self.gru_backward(self.drop(torch.flip(x, dims=[1])))
        backward = torch.flip(backward, dims=[1])
        return self.attention(x1, backward)


class _AsdModel(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.visualEncoder = _VisualEncoder()
        self.audioEncoder = _AudioEncoder()
        self.fusion = _Fusion(256)
        self.detector = _Detector(256)

    def forward_visual_frontend(self, x: torch.Tensor) -> torch.Tensor:
        batch, frames, width, height = x.shape
        x = x.view(batch, 1, frames, width, height)
        x = (x / 255.0 - 0.4161) / 0.1688
        return self.visualEncoder(x)

    def forward_audio_frontend(self, x: torch.Tensor) -> torch.Tensor:
        return self.audioEncoder(x.unsqueeze(1).transpose(2, 3))

    def forward_audio_visual_backend(
        self, audio: torch.Tensor, visual: torch.Tensor
    ) -> torch.Tensor:
        x = self.detector(self.fusion(audio, visual))
        return torch.reshape(x, (-1, 128))


class _ScoreHead(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.FC = nn.Linear(128, 2)

    def probabilities(self, x: torch.Tensor) -> torch.Tensor:
        return torch.softmax(self.FC(x.squeeze(1)), dim=-1)[:, 1]


class _VisualHead(nn.Module):
    """Retained only so official checkpoints load with their original key layout."""

    def __init__(self) -> None:
        super().__init__()
        self.FC = nn.Linear(128, 2)


class LrAsdInferenceModel(nn.Module):
    """Inference-only network with checkpoint-compatible attribute names."""

    def __init__(self) -> None:
        super().__init__()
        self.model = _AsdModel()
        self.lossAV = _ScoreHead()
        self.lossV = _VisualHead()

    def active_speaker_probabilities(
        self,
        audio_features: torch.Tensor,
        visual_features: torch.Tensor,
    ) -> torch.Tensor:
        audio = self.model.forward_audio_frontend(audio_features)
        visual = self.model.forward_visual_frontend(visual_features)
        fused = self.model.forward_audio_visual_backend(audio, visual)
        return self.lossAV.probabilities(fused)
