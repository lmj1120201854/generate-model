import torch
from torch import nn
from torch.autograd import Variable
from torch import autograd
import random

import torchvision.transforms as tfs
from torch.utils.data import DataLoader, sampler
from torchvision.datasets import MNIST

import numpy as np

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec

SEED = 1854
torch.manual_seed(SEED)
random.seed(SEED)
torch.backends.cudnn.deterministic = True

plt.rcParams['figure.figsize'] = (10.0, 8.0)  # 设置画图的尺寸
plt.rcParams['image.interpolation'] = 'nearest'
plt.rcParams['image.cmap'] = 'gray'


def show_images(images):  # 定义画图工具
    images = np.reshape(images, [images.shape[0], -1])
    sqrtn = int(np.ceil(np.sqrt(images.shape[0])))
    sqrtimg = int(np.ceil(np.sqrt(images.shape[1])))

    fig = plt.figure(figsize=(sqrtn, sqrtn))
    gs = gridspec.GridSpec(sqrtn, sqrtn)
    gs.update(wspace=0.05, hspace=0.05)

    for i, img in enumerate(images):
        ax = plt.subplot(gs[i])
        plt.axis('off')
        ax.set_xticklabels([])
        ax.set_yticklabels([])
        ax.set_aspect('equal')
        plt.imshow(img.reshape([sqrtimg, sqrtimg]))
    plt.savefig('./pic/wgan_data.png')
    plt.close()
    return 


def preprocess_img(x):
    x = tfs.ToTensor()(x)
    return (x - 0.5) / 0.5


def deprocess_img(x):
    return (x + 1.0) / 2.0


class ChunkSampler(sampler.Sampler):  # 定义一个取样的函数
    """Samples elements sequentially from some offset. 
    Arguments:
        num_samples: # of desired datapoints
        start: offset where we should start selecting from
    """
    def __init__(self, num_samples, start=0):
        self.num_samples = num_samples
        self.start = start

    def __iter__(self):
        return iter(range(self.start, self.start + self.num_samples))

    def __len__(self):
        return self.num_samples


NUM_TRAIN = 50000
NUM_VAL = 5000

NOISE_DIM = 96
batch_size = 128
n_train_step = 3  # 每训练n_train_step次判别器训练一次生成器

train_set = MNIST('./mnist', train=True, download=False, transform=preprocess_img)

train_data = DataLoader(train_set, batch_size=batch_size, sampler=ChunkSampler(NUM_TRAIN, 0))

val_set = MNIST('./mnist', train=True, download=False, transform=preprocess_img)

val_data = DataLoader(val_set, batch_size=batch_size, sampler=ChunkSampler(NUM_VAL, NUM_TRAIN))


# imgs = deprocess_img(train_data.__iter__().next()[0].view(batch_size, 784)).numpy().squeeze() # 可视化图片效果
# show_images(imgs)


# 判决网络
def discriminator():
    net = nn.Sequential(        
            nn.Linear(784, 256),
            nn.LeakyReLU(0.2),
            nn.Linear(256, 256),
            nn.LeakyReLU(0.2),
            nn.Linear(256, 1)
        )
    return net


# 生成网络
def generator(noise_dim=NOISE_DIM):   
    net = nn.Sequential(
        nn.Linear(noise_dim, 1024),
        nn.ReLU(True),
        nn.Linear(1024, 1024),
        nn.ReLU(True),
        nn.Linear(1024, 784),
        nn.Tanh()
    )
    return net


bce_loss = nn.BCEWithLogitsLoss()
# bce_loss = nn.MSELoss()


def gradient_penalty(D, xr, xf):
    """
    :param D: 判别网络
    :param xr: 真实数据
    :param xf: 生成器生成数据
    :return: 梯度惩罚损失
    """
    t = torch.rand(xr.size(0), 1).cuda()
    t = t.expand_as(xr)
    h_hat = t * xr + (1 - t) * xf
    h_hat.requires_grad_()
    pre = D(h_hat)
    grad = autograd.grad(outputs=pre, inputs=h_hat,
                         grad_outputs=torch.ones_like(pre),
                         create_graph=True, retain_graph=True, only_inputs=True)[0]
    gp = torch.pow(grad.norm(2, dim=1) - 1, 2).mean()
    return gp


class WGANLoss(nn.Module):
    def __init__(self):
        super(WGANLoss, self).__init__()

    def forward(self, fake_scores, real_scores):
        loss = torch.mean(fake_scores.detach()) - torch.mean(real_scores.detach())
        return loss


d_loss = WGANLoss().cuda


'''def discriminator_loss(D, logits_real, logits_fake, xr, xf):  # 判别器的 loss
    size = logits_real.shape[0]
    true_labels = Variable(torch.ones(size, 1)).float().cuda()
    false_labels = Variable(torch.zeros(size, 1)).float().cuda()
    loss = bce_loss(logits_real, true_labels) + bce_loss(logits_fake, false_labels) + \
           0.2 * gradient_penalty(D, xr, xf)
    return loss'''


def discriminator_loss(D, logits_real, logits_fake, xr, xf):  # 判别器的 loss
    size = logits_real.shape[0]
    true_labels = Variable(torch.ones(size, 1)).float().cuda()
    false_labels = Variable(torch.zeros(size, 1)).float().cuda()
    loss = bce_loss(logits_real, true_labels) + bce_loss(logits_fake, false_labels) + \
           0.2 * gradient_penalty(D, xr, xf)
    return loss


def generator_loss(logits_fake):  # 生成器的 loss
    size = logits_fake.shape[0]
    true_labels = Variable(torch.ones(size, 1)).float().cuda()
    loss = bce_loss(logits_fake, true_labels)
    return loss


# 使用 adam 来进行训练，学习率是 3e-4, beta1 是 0.5, beta2 是 0.999
def get_optimizer(net):
    optimizer = torch.optim.Adam(net.parameters(), lr=3e-4, betas=(0.5, 0.999))
    return optimizer


def train_a_gan(D_net, G_net, D_optimizer, G_optimizer, discriminator_loss, generator_loss, show_every=250, 
                noise_size=96, num_epochs=10):
    iter_count = 0
    for epoch in range(num_epochs):
        for x, _ in train_data:
            bs = x.shape[0]
            # 判别网络
            for step in range(n_train_step):
                real_data = Variable(x).view(bs, -1).cuda()  # 真实数据
                logits_real = D_net(real_data)  # 判别网络得分

                sample_noise = (torch.rand(bs, noise_size) - 0.5) / 0.5  # -1 ~ 1 的均匀分布
                g_fake_seed = Variable(sample_noise).cuda()
                fake_images = G_net(g_fake_seed)  # 生成的假的数据
                logits_fake = D_net(fake_images)  # 判别网络得分

                d_total_error = discriminator_loss(D_net, logits_real, logits_fake, real_data, fake_images)  # 判别器的 loss
                D_optimizer.zero_grad()
                d_total_error.backward()
                D_optimizer.step()  # 优化判别网络
            
            # 生成网络
            g_fake_seed = Variable(sample_noise).cuda()
            fake_images = G_net(g_fake_seed)  # 生成的假的数据

            gen_logits_fake = D_net(fake_images)
            g_error = generator_loss(gen_logits_fake)  # 生成网络的 loss
            G_optimizer.zero_grad()
            g_error.backward()
            G_optimizer.step()  # 优化生成网络

            if iter_count % show_every == 0:
                print('Iter: {}, D: {:.4}, G:{:.4}'.format(iter_count, d_total_error.item(), g_error.item()))
                imgs_numpy = deprocess_img(fake_images.data.cpu().numpy())
                show_images(imgs_numpy[0:16])
                plt.show()
                print()
            iter_count += 1


D = discriminator().cuda()
G = generator().cuda()

D_optim = get_optimizer(D)
G_optim = get_optimizer(G)

for epoch in range(3):
    train_a_gan(D, G, D_optim, G_optim, discriminator_loss, generator_loss)
