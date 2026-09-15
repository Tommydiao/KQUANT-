"""Training-only descriptive diagnostics. No factor selection or runtime weights."""
import numpy as np


def fit_ridge(x, y, alpha=1.):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if x.ndim != 2 or y.shape != (len(x),) or len(x)<2:
        raise ValueError('Invalid training shapes')
    if not np.isfinite(x).all() or not np.isfinite(y).all() or alpha<=0:
        raise ValueError('Invalid training values')
    mean, std = x.mean(axis=0), x.std(axis=0)
    std = np.where(std>1e-12, std, 1.)
    z = (x-mean)/std
    intercept = float(y.mean())
    coef = np.linalg.solve(z.T@z+alpha*np.eye(x.shape[1]), z.T@(y-intercept))
    return dict(mean=mean.tolist(), std=std.tolist(), coefficient=coef.tolist(), intercept=intercept)


def predict(model, x):
    return model['intercept'] + ((np.asarray(x)-model['mean'])/model['std'])@model['coefficient']


def diagnostics(x, y, names):
    x, y = np.asarray(x), np.asarray(y)
    if x.shape[1] != len(names):
        raise ValueError('Feature order mismatch')
    bins = {}
    for j,name in enumerate(names):
        edges = np.unique(np.quantile(x[:,j],[.2,.4,.6,.8]))
        membership = np.searchsorted(edges,x[:,j],side='right')
        bins[name] = {'edges':edges.tolist(), 'groups':[
            {'bucket':b,'count':int((membership==b).sum()),
             'mean_outcome':float(y[membership==b].mean()) if (membership==b).any() else None}
            for b in range(len(edges)+1)]}
    std = x.std(axis=0)
    centered = x-x.mean(axis=0)
    corr = []
    for i in range(len(names)):
        corr.append([float(np.mean(centered[:,i]*centered[:,j])/(std[i]*std[j]))
                     if std[i]>1e-12 and std[j]>1e-12 else None for j in range(len(names))])
    return {'scope':'TRAIN_ONLY_DESCRIPTIVE', 'feature_order':names,
            'correlation':corr, 'buckets':bins, 'automatic_selection':False}
