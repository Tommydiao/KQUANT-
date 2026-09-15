"""CPU-only causal quantile TCN; imports no application/execution runtime."""
import numpy as np
import copy
import os
import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader

from .sequences import transform


class CausalConv(nn.Module):
    def __init__(self, cin, cout, dilation):
        super().__init__()
        self.left = 2 * dilation
        self.conv = nn.Conv1d(cin, cout, 3, dilation=dilation)

    def forward(self, x):
        return self.conv(nn.functional.pad(x, (self.left, 0)))


class Block(nn.Module):
    def __init__(self, cin, dilation):
        super().__init__()
        self.body = nn.Sequential(CausalConv(cin, 32, dilation), nn.ReLU(), nn.Dropout(.1),
                                  CausalConv(32, 32, dilation), nn.ReLU(), nn.Dropout(.1))
        self.skip = nn.Conv1d(cin, 32, 1) if cin != 32 else nn.Identity()

    def forward(self, x):
        return nn.functional.relu(self.body(x) + self.skip(x))


class PathTCN(nn.Module):
    def __init__(self, single_scale=False):
        super().__init__()
        self.single_scale = single_scale
        self.branches = nn.ModuleList([nn.Sequential(*[Block(5 if i == 0 else 32, 2 ** i) for i in range(7)])
                                      for _ in range(1 if single_scale else 3)])
        self.head = nn.Linear(32 * len(self.branches), 72)

    def forward(self, xs):
        z = torch.cat([branch(x.transpose(1, 2))[:, :, -1] for branch, x in zip(self.branches, xs)], dim=1)
        raw = self.head(z).reshape(-1, 24, 3)
        median = raw[:, :, 1]
        return torch.stack([median - nn.functional.softplus(raw[:, :, 0]), median,
                            median + nn.functional.softplus(raw[:, :, 2])], dim=-1)


def loss(prediction, y):
    error = y.unsqueeze(-1) - prediction
    quantiles = prediction.new_tensor([.1, .5, .9])
    return torch.maximum(quantiles * error, (quantiles - 1) * error).mean()


class Windows(Dataset):
    def __init__(self, panel, rows, fitted):
        self.panel, self.rows, self.fitted = panel, rows, fitted

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        row = self.rows[i]
        xs = [torch.from_numpy(x[0].astype(np.float32)) for x in transform(self.panel.batch([row]), self.fitted)]
        return xs, torch.from_numpy(self.panel.outcomes([row])[0])


def fit(panel, train, validation, fitted, settings, seed, directory, single=False):
    from .contracts import atomic_json, read_json, file_hash
    if not train or not validation:
        raise ValueError("Empty train or validation partition")
    torch.set_num_threads(settings["cpu_threads"])
    torch.manual_seed(seed)
    np.random.seed(seed)
    torch.use_deterministic_algorithms(True)
    model = PathTCN(single)
    optimizer = torch.optim.AdamW(model.parameters(), lr=settings["learning_rate"], weight_decay=settings["weight_decay"])
    generator = torch.Generator().manual_seed(seed)
    loader = DataLoader(Windows(panel, train, fitted), batch_size=settings["batch_size"], shuffle=True, generator=generator)
    val_loader = DataLoader(Windows(panel, validation, fitted), batch_size=settings["batch_size"])
    best, wait, history, best_state = float("inf"), 0, [], None
    checkpoints = sorted(directory.glob("checkpoint_*.json"))
    if checkpoints:
        meta = read_json(checkpoints[-1])
        saved = directory / meta["file"]
        if file_hash(saved) != meta["sha256"]:
            raise ValueError("Checkpoint integrity mismatch")
        state = torch.load(saved, map_location="cpu", weights_only=True)
        model.load_state_dict(state["model"])
        optimizer.load_state_dict(state["optimizer"])
        torch.set_rng_state(state["rng"])
        generator.set_state(state["generator"])
        best, wait, history, best_state = state["best"], state["wait"], state["history"], state["best_state"]
    for epoch in range(len(history), settings["epochs"]):
        if wait >= settings["patience"]:
            break
        model.train()
        total, count = 0., 0
        for xs, y in loader:
            optimizer.zero_grad()
            error = loss(model(xs), y)
            if not torch.isfinite(error):
                raise ValueError("Non-finite training loss")
            error.backward()
            optimizer.step()
            total += error.item() * len(y)
            count += len(y)
        model.eval()
        vtotal, vcount = 0., 0
        with torch.no_grad():
            for xs, y in val_loader:
                error = loss(model(xs), y)
                vtotal += error.item() * len(y)
                vcount += len(y)
        score = vtotal / vcount
        history.append({"epoch": epoch + 1, "train_pinball": total / count, "validation_pinball": score})
        atomic_json(directory / "training_curve.json", history)
        print("epoch", epoch + 1, "validation", score, flush=True)
        if score < best:
            best, wait = score, 0
            best_state = copy.deepcopy(model.state_dict())
        else:
            wait += 1
        name = f"checkpoint_{epoch + 1:03d}.pt"
        final = directory / name
        temporary = directory / (name + ".tmp")
        if final.exists():
            final.rename(directory / (name + f".uncommitted_{os.getpid()}"))
        torch.save({"model": model.state_dict(), "optimizer": optimizer.state_dict(), "rng": torch.get_rng_state(),
                    "generator": generator.get_state(), "history": history, "best": best, "wait": wait,
                    "best_state": best_state}, temporary)
        os.replace(temporary, final)
        atomic_json(directory / f"checkpoint_{epoch + 1:03d}.json", {"file": name, "sha256": file_hash(final)})
    if best_state is None:
        raise ValueError("No finite trained checkpoint")
    torch.save(best_state, directory / "weights.pt")
    return {"epochs": len(history), "best_validation_pinball": best, "seed": seed,
            "parameters": sum(p.numel() for p in model.parameters()), "single_scale": single}
