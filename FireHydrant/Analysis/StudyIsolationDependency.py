#!/usr/bin/env python
"""
leptonejet isolation dependency of pT, eta
"""
import argparse
from contextlib import contextmanager

import awkward
import coffea.processor as processor
import numpy as np
from coffea import hist
from coffea.analysis_objects import JaggedCandidateArray
from FireHydrant.Analysis.DatasetMapLoader import (DatasetMapLoader,
                                                   SigDatasetMapLoader)
from FireHydrant.Tools.correction import (get_nlo_weight_function,
                                          get_pu_weights_function,
                                          get_ttbar_weight)
from FireHydrant.Tools.metfilter import MetFilters
from FireHydrant.Tools.trigger import Triggers

parser = argparse.ArgumentParser(description="leptonjet isolation profile of pt, eta")
parser.add_argument("--sync", action='store_true', help="issue rsync command to sync plots folder to lxplus web server")
parser.add_argument("--preserve", action='store_true', help="preserve plots in ROOT file")
args = parser.parse_args()

import ROOT
ROOT.gROOT.SetBatch()


sdml = SigDatasetMapLoader()
sigDS, sigSCALE = sdml.fetch()

dml = DatasetMapLoader()
bkgDS, bkgMAP, bkgSCALE = dml.fetch('bkg')
dataDS, dataMAP = dml.fetch('data')


@contextmanager
def _setIgnoreLevel(level):
    originalLevel = ROOT.gErrorIgnoreLevel
    ROOT.gErrorIgnoreLevel = level
    yield
    ROOT.gErrorIgnoreLevel = originalLevel

"""Leptonjet isolation, pt, """
class LeptonjetIsoProcessor(processor.ProcessorABC):
    def __init__(self, dphi_control=False, data_type='sig'):
        self.dphi_control = dphi_control
        self.data_type = data_type

        dataset_axis = hist.Cat('dataset', 'dataset')
        self._accumulator = processor.dict_accumulator({
            'all05': processor.column_accumulator(np.zeros(shape=(0,))),
            'nopu05': processor.column_accumulator(np.zeros(shape=(0,))),
            'dbeta': processor.column_accumulator(np.zeros(shape=(0,))),
            'all05w': processor.column_accumulator(np.zeros(shape=(0,))),
            'nopu05w': processor.column_accumulator(np.zeros(shape=(0,))),
            'dbetaw': processor.column_accumulator(np.zeros(shape=(0,))),
            'pt': processor.column_accumulator(np.zeros(shape=(0,))),
            'eta': processor.column_accumulator(np.zeros(shape=(0,))),
            'wgt': processor.column_accumulator(np.zeros(shape=(0,))),
            'ljtype': processor.column_accumulator(np.zeros(shape=(0,))),
            'channel': processor.column_accumulator(np.zeros(shape=(0,))),
        })

        self.pucorrs = get_pu_weights_function()
        ## NOT applied for now
        self.nlo_w = get_nlo_weight_function('w')
        self.nlo_z = get_nlo_weight_function('z')

    @property
    def accumulator(self):
        return self._accumulator

    def process(self, df):
        output = self.accumulator.identity()
        if df.size==0: return output

        dataset = df['dataset']
        ## construct weights ##
        wgts = processor.Weights(df.size)
        if self.data_type!='data':
            wgts.add('genw', df['weight'])
            npv = df['trueInteractionNum']
            wgts.add('pileup', *(f(npv) for f in self.pucorrs))

        triggermask = np.logical_or.reduce([df[t] for t in Triggers])
        wgts.add('trigger', triggermask)
        cosmicpairmask = df['cosmicveto_result']
        wgts.add('cosmicveto', cosmicpairmask)
        pvmask = df['metfilters_PrimaryVertexFilter']
        wgts.add('primaryvtx', pvmask)
        # ...bla bla, other weights goes here

        weight = wgts.weight()
        ########################

        leptonjets = JaggedCandidateArray.candidatesfromcounts(
            df['pfjet_p4'],
            px=df['pfjet_p4.fCoordinates.fX'],
            py=df['pfjet_p4.fCoordinates.fY'],
            pz=df['pfjet_p4.fCoordinates.fZ'],
            energy=df['pfjet_p4.fCoordinates.fT'],
            pfisoAll05=df['pfjet_pfIsolation05'],
            pfisoNopu05=df['pfjet_pfIsolationNoPU05'],
            pfisoDbeta=df['pfjet_pfiso'],
            ncands=df['pfjet_pfcands_n'],
        )
        ljdautype = awkward.fromiter(df['pfjet_pfcand_type'])
        npfmu = (ljdautype==3).sum()
        ndsa = (ljdautype==8).sum()
        isegammajet = (npfmu==0)&(ndsa==0)
        ispfmujet = (npfmu>=2)&(ndsa==0)
        isdsajet = ndsa>0
        label = isegammajet.astype(int)*1+ispfmujet.astype(int)*2+isdsajet.astype(int)*3
        leptonjets.add_attributes(label=label)
        nmu = ((ljdautype==3)|(ljdautype==8)).sum()
        leptonjets.add_attributes(ismutype=(nmu>=2), iseltype=(nmu==0))

        ## __twoleptonjets__
        twoleptonjets = leptonjets.counts>=2
        dileptonjets = leptonjets[twoleptonjets]
        wgt = weight[twoleptonjets]

        if dileptonjets.size==0: return output
        lj0 = dileptonjets[dileptonjets.pt.argmax()]
        lj1 = dileptonjets[dileptonjets.pt.argsort()[:, 1:2]]

        ## channel def ##
        singleMuljEvents = dileptonjets.ismutype.sum()==1
        muljInLeading2Events = (lj0.ismutype | lj1.ismutype).flatten()
        channel_2mu2e = (singleMuljEvents&muljInLeading2Events).astype(int)*1

        doubleMuljEvents = dileptonjets.ismutype.sum()==2
        muljIsLeading2Events = (lj0.ismutype & lj1.ismutype).flatten()
        channel_4mu = (doubleMuljEvents&muljIsLeading2Events).astype(int)*2

        channel_ = channel_2mu2e + channel_4mu
        ###########

        isControl = (np.abs(lj0.p4.delta_phi(lj1.p4))<np.pi/2).flatten()

        ## __isControl__
        if self.dphi_control:
            dileptonjets = dileptonjets[isControl]
            wgt = wgt[isControl]
            lj0 = lj0[isControl]
            lj1 = lj1[isControl]
            channel_ = channel_[isControl]
        else:
            dileptonjets = dileptonjets
        if dileptonjets.size==0: return output


        if self.data_type == 'bkg':
            wgt *= bkgSCALE[dataset]

        output['all05'] += processor.column_accumulator(dileptonjets.pfisoAll05.flatten())
        output['nopu05'] += processor.column_accumulator(dileptonjets.pfisoNopu05.flatten())
        output['dbeta'] += processor.column_accumulator(dileptonjets.pfisoDbeta.flatten())
        output['all05w'] += processor.column_accumulator((dileptonjets.pfisoAll05/dileptonjets.ncands).flatten())
        output['nopu05w'] += processor.column_accumulator((dileptonjets.pfisoNopu05/dileptonjets.ncands).flatten())
        output['dbetaw'] += processor.column_accumulator((dileptonjets.pfisoDbeta/dileptonjets.ncands).flatten())
        output['pt'] += processor.column_accumulator(dileptonjets.pt.flatten())
        output['eta'] += processor.column_accumulator(dileptonjets.eta.flatten())
        output['wgt'] += processor.column_accumulator((dileptonjets.pt.ones_like()*wgt).flatten())
        output['ljtype'] += processor.column_accumulator((dileptonjets.ismutype.astype(int)*1+dileptonjets.iseltype.astype(int)*2).flatten())
        output['channel'] += processor.column_accumulator((dileptonjets.pt.ones_like()*channel_).flatten())

        return output

    def postprocess(self, accumulator):
        return accumulator


def root_filling(output, datatype):

    maxPt = 600 if datatype=='sig' else 300

    hprofs_pt, hprofs_eta = {}, {}
    for chan in ['4mu', '2mu2e']:
        for ljtype in ['mu', 'egm']:
            for iso in ['all05', 'nopu05', 'dbeta']:
                key = f'{chan}_{ljtype}_{iso}'
                hprofs_pt[key] = ROOT.TProfile(f'{datatype}-pt__{key}', ';pT [GeV];isolation', 100, 0, maxPt, 0, 1)
                hprofs_pt[key+'w'] = ROOT.TProfile(f'{datatype}-pt__{key}w', ';pT [GeV];isolation', 100, 0, maxPt, 0, 1)
                hprofs_eta[key] = ROOT.TProfile(f'{datatype}-eta__{key}', ';eta;isolation', 50, -2.5, 2.5, 0, 1)

    CHANNEL = {1: '2mu2e', 2: '4mu'}
    LJTYPE = {1: 'mu', 2: 'egm'}

    for all05_, nopu05_, dbeta_, all05w_, nopu05w_, dbetaw_, pt_, eta_, wgt_, ljtype_, chan_ in np.nditer([
        output['all05'].value,
        output['nopu05'].value,
        output['dbeta'].value,
        output['all05w'].value,
        output['nopu05w'].value,
        output['dbetaw'].value,
        output['pt'].value,
        output['eta'].value,
        output['wgt'].value,
        output['ljtype'].value,
        output['channel'].value,]):
        if chan_ not in [1,2]: continue
        if ljtype_ not in [1,2]: continue
        key_ = f'{CHANNEL[int(chan_)]}_{LJTYPE[int(ljtype_)]}'
        hprofs_pt[f'{key_}_all05'].Fill(pt_, all05_, wgt_)
        hprofs_pt[f'{key_}_nopu05'].Fill(pt_, nopu05_, wgt_)
        hprofs_pt[f'{key_}_dbeta'].Fill(pt_, dbeta_, wgt_)

        hprofs_pt[f'{key_}_all05w'].Fill(pt_, all05w_, wgt_)
        hprofs_pt[f'{key_}_nopu05w'].Fill(pt_, nopu05w_, wgt_)
        hprofs_pt[f'{key_}_dbetaw'].Fill(pt_, dbetaw_, wgt_)

        hprofs_eta[f'{key_}_all05'].Fill(eta_, all05_, wgt_)
        hprofs_eta[f'{key_}_nopu05'].Fill(eta_, nopu05_, wgt_)
        hprofs_eta[f'{key_}_dbeta'].Fill(eta_, dbeta_, wgt_)

    return hprofs_pt, hprofs_eta


if __name__ == "__main__":
    import os
    from os.path import join, isdir

    outdir = join(os.getenv('FH_BASE'), "Imgs", __file__.split('.')[0])
    if not isdir(outdir): os.makedirs(outdir)

    hprofs_pt, hprofs_eta = {}, {}

    print('[signal]')
    output = processor.run_uproot_job(sigDS,
                                      treename='ffNtuplizer/ffNtuple',
                                      processor_instance=LeptonjetIsoProcessor(),
                                      executor=processor.futures_executor,
                                      executor_args=dict(workers=12, flatten=True),
                                      chunksize=500000,
                                      )


    print("Filling..")
    hprofs_pt['sig'], hprofs_eta['sig'] = root_filling(output, 'sig')

    print("Saving...")
    c = ROOT.TCanvas('c', 'canvas', 700, 500)
    for k, hprof in hprofs_pt['sig'].items():
        hprof.Draw()
        c.Draw()
        with _setIgnoreLevel(ROOT.kError):
            c.SaveAs(f'{outdir}/sig-pt__{k}.png')
            c.SaveAs(f'{outdir}/sig-pt__{k}.pdf')
        c.Clear()
    for k, hprof in hprofs_eta['sig'].items():
        hprof.Draw()
        c.Draw()
        with _setIgnoreLevel(ROOT.kError):
            c.SaveAs(f'{outdir}/sig-eta__{k}.png')
            c.SaveAs(f'{outdir}/sig-eta__{k}.pdf')
        c.Clear()


    print('[background]')
    output = processor.run_uproot_job(bkgDS,
                                      treename='ffNtuplizer/ffNtuple',
                                      processor_instance=LeptonjetIsoProcessor(data_type='bkg'),
                                      executor=processor.futures_executor,
                                      executor_args=dict(workers=12, flatten=True),
                                      chunksize=500000,
                                      )


    print("Filling..")
    hprofs_pt['bkg'], hprofs_eta['bkg'] = root_filling(output, 'bkg')

    print("Saving...")
    for k, hprof in hprofs_pt['bkg'].items():
        hprof.Draw()
        c.Draw()
        with _setIgnoreLevel(ROOT.kError):
            c.SaveAs(f'{outdir}/bkg-pt__{k}.png')
            c.SaveAs(f'{outdir}/bkg-pt__{k}.pdf')
        c.Clear()
    for k, hprof in hprofs_eta['bkg'].items():
        hprof.Draw()
        c.Draw()
        with _setIgnoreLevel(ROOT.kError):
            c.SaveAs(f'{outdir}/bkg-eta__{k}.png')
            c.SaveAs(f'{outdir}/bkg-eta__{k}.pdf')
        c.Clear()


    print('[data]')
    output = processor.run_uproot_job(dataDS,
                                      treename='ffNtuplizer/ffNtuple',
                                      processor_instance=LeptonjetIsoProcessor(dphi_control=True, data_type='data'),
                                      executor=processor.futures_executor,
                                      executor_args=dict(workers=12, flatten=True),
                                      chunksize=500000,
                                      )


    print("Filling..")
    hprofs_pt['data'], hprofs_eta['data'] = root_filling(output, 'data')

    print("Saving...")
    for k, hprof in hprofs_pt['data'].items():
        hprof.Draw()
        c.Draw()
        with _setIgnoreLevel(ROOT.kError):
            c.SaveAs(f'{outdir}/data-pt__{k}.png')
            c.SaveAs(f'{outdir}/data-pt__{k}.pdf')
        c.Clear()
    for k, hprof in hprofs_eta['data'].items():
        hprof.Draw()
        c.Draw()
        with _setIgnoreLevel(ROOT.kError):
            c.SaveAs(f'{outdir}/data-eta__{k}.png')
            c.SaveAs(f'{outdir}/data-eta__{k}.pdf')
        c.Clear()

    c.Close()


    overlayCanvas_pt = {}
    COLORS = [ROOT.kBlue, ROOT.kRed, ROOT.kGreen]
    for k in hprofs_pt['sig']:
        overlayCanvas_pt[k] = ROOT.TCanvas(f'overlay-pt__{k}', '', 700, 500)
        overlayCanvas_pt[k].cd()
        overlayCanvas_pt[k].SetLogx()
        x1, y1, height = None, None, None
        profs = [hprofs_pt['sig'][k], hprofs_pt['bkg'][k], hprofs_pt['data'][k]]
        for i, h in enumerate(profs):
            h.SetLineColor(COLORS[i])
            if 'all05' in k:
                h.GetYaxis().SetRangeUser(0, 0.8)
            if 'nopu05' in k:
                h.GetYaxis().SetRangeUser(0, 0.5)
            if 'dbeta' in k:
                h.GetYaxis().SetRangeUser(0, 0.3)
            if i==0: h.Draw()
            else: h.Draw('same')
            ROOT.gPad.Update() # this is needed, otherwise `FindObject('stats')` would return null ptr.
            statbox = h.FindObject('stats')
            if i==0:
                x1, y1 = statbox.GetX1NDC(), statbox.GetY1NDC()
                height = statbox.GetY2NDC()-statbox.GetY1NDC()
            else:
                statbox.SetY2NDC(y1)
                y1 -= height
                statbox.SetY1NDC(y1)
            statbox.SetTextColor(COLORS[i])
            overlayCanvas_pt[k].Update()
        with _setIgnoreLevel(ROOT.kError):
            overlayCanvas_pt[k].SaveAs(f'{outdir}/overlay-pt__{k}.png')
            overlayCanvas_pt[k].SaveAs(f'{outdir}/overlay-pt__{k}.pdf')


    if args.preserve:
        outrootfn = f'{outdir}/plots.root'
        print(f"--> preserving")
        outrootf = ROOT.TFile(outrootfn, 'RECREATE')
        outrootf.cd()
        for hprofs in hprofs_pt.values():
            for hprof in hprofs.values():
                hprof.Write()
        for hprofs in hprofs_eta.values():
            for hprof in hprofs.values():
                hprof.Write()
        for c in overlayCanvas_pt.values():
            c.Write()
            c.Close()
        outrootf.Close()


    if args.sync:
        webdir = 'wsi@lxplus.cern.ch:/eos/user/w/wsi/www/public/firehydrant'
        cmd = f'rsync -az --exclude ".*" --delete {outdir} {webdir}'
        print(f"--> sync with: {webdir}")
        os.system(cmd)

    print("Done.")
