""" Full assembly of the parts to form the complete network """

import torch.nn.functional as F
import scipy
from .unet_parts import *

class UNet(nn.Module):
    def __init__(self, n_channels_in, n_channels_out, bilinear=True):
        super(UNet, self).__init__()
        self.n_channels_in = n_channels_in
        self.n_channels_out = n_channels_out
        self.bilinear = bilinear

        self.inc = DoubleConv(n_channels_in, 32)
        self.down1 = Down(32, 64)
        self.down2 = Down(64, 128)
        self.down3 = Down(128, 256)
        factor = 2 if bilinear else 1
        self.down4 = Down(256, 512 // factor)
        self.up1 = Up(512, 256 // factor, bilinear)
        self.up2 = Up(256, 128 // factor, bilinear)
        self.up3 = Up(128, 64 // factor, bilinear)
        self.up4 = Up(64, 32, bilinear)
        self.outc = OutConv(32, n_channels_out)

    def forward(self, x):
        x1 = self.inc(x)
        x2 = self.down1(x1)
        x3 = self.down2(x2)
        x4 = self.down3(x3)
        x5 = self.down4(x4)
        x = self.up1(x5, x4)
        x = self.up2(x, x3)
        x = self.up3(x, x2)
        x = self.up4(x, x1)
        out = self.outc(x)
        return out

class WNet(nn.Module):

    def __init__(self, args, masked_kspace=True):
        super(WNet, self).__init__()

        self.bilinear = args.bilinear
        self.args = args
        self.masked_kspace = masked_kspace

        mask_path = args.mask_path
        mat = scipy.io.loadmat(mask_path)
        #TODO: fix hard cooded mask reader
        self.mask = torch.tensor(mat['mask_2'], device=self.args.device)
        self.maskNot = self.mask == 0

        self.kspace_Unet = UNet(n_channels_in=args.NumInputSlices*2, n_channels_out=2, bilinear=self.bilinear)
        self.img_UNet = UNet(n_channels_in=1, n_channels_out=1, bilinear=self.bilinear)

    def fftshift(self, img):

        S = int(img.shape[3]/2)
        img2 = torch.zeros_like(img)
        img2[:, :, :S, :S] = img[:, :, S:, S:]
        img2[:, :, S:, S:] = img[:, :, :S, :S]
        img2[:, :, :S, S:] = img[:, :, S:, :S]
        img2[:, :, S:, :S] = img[:, :, :S, S:]
        return img2

    def inverseFT(self, Kspace):
        Kspace = Kspace.permute(0, 2, 3, 1)
        img_cmplx = torch.ifft(Kspace, 2)
        img = torch.sqrt(img_cmplx[:, :, :, 0]**2 + img_cmplx[:, :, :, 1]**2)
        img = img[:,None, :, :]
        return img

    def forward(self, Kspace):

        rec_all_Kspace = self.kspace_Unet(Kspace)
        if self.masked_kspace:
            rec_Kspace = self.mask*Kspace[:, int(Kspace.shape[1]/2)-1:int(Kspace.shape[1]/2)+1, :, :] +\
                         self.maskNot*rec_all_Kspace
            F_rec_Kspace = self.inverseFT(rec_Kspace)
        else:
            rec_Kspace = rec_all_Kspace
            F_rec_Kspace = self.fftshift(self.inverseFT(rec_Kspace))
        refine_Img = self.img_UNet(F_rec_Kspace)
        rec_img = torch.tanh(refine_Img + F_rec_Kspace)

        # if self.train():
        return rec_img, rec_Kspace, F_rec_Kspace

